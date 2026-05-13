"""Generate pyATS testbed YAML from device inventory."""

import yaml
import structlog

from config import settings
from db.tables import Device

log = structlog.get_logger()

# Map Parity platform names to pyATS os values
PLATFORM_TO_OS = {
    "iosxe": "iosxe",
    "ios-xe": "iosxe",
    "iosv": "iosxe",
    "ios": "ios",
    "nxos": "nxos",
    "nx-os": "nxos",
    "iosxr": "iosxr",
    "ios-xr": "iosxr",
    "asa": "asa",
    "linux": "linux",
}


def generate_testbed(devices: list[Device]) -> dict:
    """Build a pyATS testbed dict from a list of Device ORM objects.

    Credentials use %ENV{} syntax so pyATS reads them from the
    environment at runtime — no secrets in the YAML.
    """
    testbed = {
        "testbed": {"name": "parity-lab"},
        "devices": {},
    }

    # Platforms pyATS cannot handle — skip silently
    UNSUPPORTED_PLATFORMS = {"fortinet", "fortigate", "fortios"}

    for device in devices:
        if device.platform.lower() in UNSUPPORTED_PLATFORMS:
            log.info("testbed_skip_unsupported", hostname=device.hostname, platform=device.platform)
            continue
        os_type = PLATFORM_TO_OS.get(device.platform.lower(), device.platform.lower())

        testbed["devices"][device.hostname] = {
            "os": os_type,
            "type": device.device_type,
            "connections": {
                "defaults": {"class": "unicon.Unicon"},
                "ssh": {
                    "protocol": "ssh",
                    "ip": device.management_ip,
                    "port": 22,
                    "settings": {
                        "GRACEFUL_DISCONNECT_WAIT_SEC": 0,
                        "POST_DISCONNECT_WAIT_SEC": 0,
                    },
                },
            },
            "credentials": {
                "default": {
                    "username": "%ENV{PYATS_USERNAME}",
                    "password": "%ENV{PYATS_PASSWORD}",
                },
            },
            "custom": {
                "parity_device_id": device.id,
            },
        }

    log.info("testbed_generated", device_count=len(devices))
    return testbed


def generate_testbed_yaml(devices: list[Device]) -> str:
    """Return the testbed as a YAML string."""
    return yaml.dump(generate_testbed(devices), default_flow_style=False, sort_keys=False)
