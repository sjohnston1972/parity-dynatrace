"""Grafana API client for pulling device inventory.

Discovers network devices by querying InfluxDB datasources via
Grafana's datasource proxy API.  Supports both Prometheus and
InfluxDB backends — the homelab uses Telegraf → InfluxDB with
'cisco' and 'fortinet' measurements.
"""

from datetime import datetime, timezone

import structlog
import httpx
from urllib.parse import quote

from config import settings

log = structlog.get_logger()

# InfluxDB measurements written by Telegraf SNMP inputs.
# Each measurement has tags: hostname, agent_host, site (cisco) or hostname (fortinet).
INFLUX_MEASUREMENTS = ["cisco", "fortinet"]

# Map measurement name → device platform / type defaults
MEASUREMENT_DEFAULTS: dict[str, dict[str, str]] = {
    "cisco": {"platform": "iosxe", "device_type": "router"},
    "fortinet": {"platform": "fortinet", "device_type": "firewall"},
}


class GrafanaClient:
    def __init__(self) -> None:
        self.base_url = settings.grafana_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.grafana_api_key}",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str) -> dict | list:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{self.base_url}{path}", headers=self.headers
            )
            r.raise_for_status()
            return r.json()

    async def health(self) -> dict:
        return await self._get("/api/health")

    async def get_datasources(self) -> list[dict]:
        return await self._get("/api/datasources")

    async def search_dashboards(self, query: str = "") -> list[dict]:
        return await self._get(f"/api/search?query={query}&type=dash-db")

    async def get_dashboard(self, uid: str) -> dict:
        return await self._get(f"/api/dashboards/uid/{uid}")

    # ── InfluxDB discovery ───────────────────────────────────

    async def _influx_query(self, datasource_uid: str, query: str) -> list[dict]:
        """Execute an InfluxQL query via Grafana's datasource proxy."""
        encoded = quote(query)
        path = f"/api/datasources/proxy/uid/{datasource_uid}/query?db=snmp&q={encoded}"
        try:
            result = await self._get(path)
            return result.get("results", [])
        except Exception as e:
            log.warning("influx_query_failed", datasource_uid=datasource_uid, error=str(e))
            return []

    async def _discover_influx_devices(self, datasource_uid: str) -> list[dict]:
        """Discover devices from InfluxDB measurements via Grafana proxy.

        For each measurement (cisco, fortinet), queries the latest data point
        grouped by hostname/agent_host/site to discover all active devices.
        """
        devices: list[dict] = []

        for measurement in INFLUX_MEASUREMENTS:
            defaults = MEASUREMENT_DEFAULTS.get(measurement, {})

            # Query to get hostname, agent_host (management IP), and site for each device
            query = (
                f'SELECT last("uptime") FROM "{measurement}" '
                f'GROUP BY "hostname", "agent_host", "site"'
            )
            results = await self._influx_query(datasource_uid, query)

            for result in results:
                for series in result.get("series", []):
                    tags = series.get("tags", {})
                    hostname = tags.get("hostname", "")
                    if not hostname:
                        continue

                    agent_host = tags.get("agent_host", "")
                    site = tags.get("site", "")

                    # Determine device_type from hostname pattern
                    device_type = defaults.get("device_type", "unknown")
                    hostname_upper = hostname.upper().split(".")[0]
                    if "-S" in hostname_upper and hostname_upper.split("-")[-1].startswith("S"):
                        device_type = "switch"
                    elif "-R" in hostname_upper and hostname_upper.split("-")[-1].startswith("R"):
                        device_type = "router"
                    elif "-FW" in hostname_upper or "FW" in hostname_upper:
                        device_type = "firewall"

                    device_tags = {}
                    if site:
                        device_tags["site"] = site
                    device_tags["measurement"] = measurement

                    # last_seen is the timestamp of the most recent telemetry point
                    # for this device — proves Telegraf actually saw it, not just that
                    # the inventory list was synced.
                    last_seen = _extract_last_timestamp(series)

                    devices.append({
                        "hostname": hostname,
                        "management_ip": agent_host or hostname,
                        "platform": defaults.get("platform", "unknown"),
                        "device_type": device_type,
                        "grafana_source": f"influxdb/snmp/{measurement}",
                        "tags": device_tags,
                        "last_seen": last_seen,
                    })

        log.info(
            "influx_discover_complete",
            device_count=len(devices),
            measurements=INFLUX_MEASUREMENTS,
        )
        return devices

    # ── Prometheus discovery (kept for compatibility) ─────────

    async def _get_prometheus_targets(self, datasource_uid: str) -> list[dict]:
        try:
            result = await self._get(
                f"/api/datasources/proxy/uid/{datasource_uid}/api/v1/targets"
            )
            return result.get("data", {}).get("activeTargets", [])
        except Exception as e:
            log.warning("grafana_targets_failed", datasource_uid=datasource_uid, error=str(e))
            return []

    async def _discover_prometheus_devices(self, datasource_uid: str, ds_name: str) -> list[dict]:
        devices: list[dict] = []
        targets = await self._get_prometheus_targets(datasource_uid)

        for target in targets:
            labels = target.get("labels", {})
            job = labels.get("job", "")
            if "snmp" not in job.lower() and not labels.get("device_type"):
                continue

            hostname = labels.get("hostname") or labels.get("instance", "").split(":")[0]
            if not hostname:
                continue

            devices.append({
                "hostname": hostname,
                "management_ip": labels.get("management_ip", labels.get("instance", "").split(":")[0]),
                "platform": labels.get("platform", "unknown"),
                "device_type": labels.get("device_type", "unknown"),
                "grafana_source": ds_name,
                "tags": {
                    k: v for k, v in labels.items()
                    if k not in {"hostname", "management_ip", "platform", "device_type", "instance", "job", "__name__"}
                },
            })

        return devices

    # ── Main discovery entrypoint ────────────────────────────

    async def discover_devices(self) -> list[dict]:
        """Discover network devices from all Grafana datasources.

        Supports both InfluxDB and Prometheus datasources.
        """
        devices: list[dict] = []
        datasources = await self.get_datasources()

        for ds in datasources:
            ds_type = ds.get("type", "")
            ds_uid = ds.get("uid", "")

            if ds_type == "influxdb":
                found = await self._discover_influx_devices(ds_uid)
                devices.extend(found)
            elif ds_type == "prometheus":
                found = await self._discover_prometheus_devices(ds_uid, ds.get("name", ""))
                devices.extend(found)

        log.info("grafana_discover_complete", device_count=len(devices))
        return devices


def _extract_last_timestamp(series: dict) -> datetime | None:
    """Pull the most recent timestamp from an InfluxQL series response.

    The 'time' column may be ISO8601 (default) or epoch ms (when Grafana
    sends epoch=ms). Returns None if it can't be parsed.
    """
    columns = series.get("columns") or []
    values = series.get("values") or []
    if not columns or not values:
        return None
    try:
        time_idx = columns.index("time")
    except ValueError:
        return None
    raw = values[-1][time_idx]
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    if isinstance(raw, str):
        # Influx returns "2026-05-10T07:30:00Z"
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


grafana_client = GrafanaClient()
