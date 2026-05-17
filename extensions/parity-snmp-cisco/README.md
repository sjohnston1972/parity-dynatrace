# parity-snmp-cisco — Dynatrace SNMP Generic extension v2

Polls the 19 Parity-managed devices over SNMPv2c, emits metrics directly
into the Dynatrace tenant tagged with `device.label`, `device.ip`, and
`site` dimensions so dashboards can pivot per-site / per-device.

## Metrics emitted

| Group | OID | Metric name | Type |
|---|---|---|---|
| cisco_system | 1.3.6.1.2.1.1.3.0 | parity.snmp.sysUptime | count (TimeTicks) |
| cisco_system | 1.3.6.1.4.1.9.2.1.58.0 | parity.snmp.cisco.cpu_5min | gauge (%) |
| cisco_system | 1.3.6.1.4.1.9.9.48.1.1.1.5.1 | parity.snmp.cisco.mem_used_bytes | gauge |
| cisco_system | 1.3.6.1.4.1.9.9.48.1.1.1.6.1 | parity.snmp.cisco.mem_free_bytes | gauge |
| cisco_interface | 1.3.6.1.2.1.2.2.1.8 | parity.snmp.if.operStatus | gauge |
| cisco_interface | 1.3.6.1.2.1.2.2.1.7 | parity.snmp.if.adminStatus | gauge |
| cisco_interface | 1.3.6.1.2.1.31.1.1.1.6 | parity.snmp.if.inOctets | count (64-bit) |
| cisco_interface | 1.3.6.1.2.1.31.1.1.1.10 | parity.snmp.if.outOctets | count (64-bit) |
| cisco_interface | 1.3.6.1.2.1.2.2.1.14 | parity.snmp.if.inErrors | count |
| cisco_interface | 1.3.6.1.2.1.2.2.1.20 | parity.snmp.if.outErrors | count |
| cisco_interface | 1.3.6.1.2.1.2.2.1.13 | parity.snmp.if.inDiscards | count |
| cisco_interface | 1.3.6.1.2.1.2.2.1.19 | parity.snmp.if.outDiscards | count |

Poll interval: **60 s** per group.

## Install + activate

Prerequisites:
1. A Dynatrace ActiveGate is registered with the tenant and reachable
   on the management subnet (192.168.20.0/24). See
   `docker/dynatrace-activegate/` in this repo.
2. The OAuth client in `.env` has scopes
   `environment-api:extensions:read`, `environment-api:extensions:write`,
   `environment-api:extension-configurations:read`, and
   `environment-api:extension-configurations:write`.

Then run:

```
py scripts/deploy_snmp_extension.py
```

The script:
1. Packages `extensions/parity-snmp-cisco/extension.yaml` into a signed
   zip (the SNMP Generic extension framework handles signing on the
   tenant side when uploaded via `/api/v2/extensions`).
2. Uploads to the tenant.
3. Activates one monitoring configuration per device from
   `_discover_devices()` (the same inventory the rest of `dynatrace_setup.py`
   uses), pinning each to the deployed ActiveGate group.
4. Verifies that metrics are landing within 90 s by querying
   `fetch metric.series parity.snmp.if.operStatus` via DQL.

## DQL examples

```dql
// Top 10 interfaces by 1h ifInOctets delta
fetch metric.series parity.snmp.if.inOctets, from:-1h
| filter source == "dt-snmp"
| summarize bytes = max(value) - min(value), by: { device.label, ifDescr }
| sort bytes desc
| limit 10
```

```dql
// Devices reporting CPU 5min > 50%
fetch metric.series parity.snmp.cisco.cpu_5min, from:-15m
| summarize cpu = avg(value), by: { device.label }
| filter cpu > 50
```
