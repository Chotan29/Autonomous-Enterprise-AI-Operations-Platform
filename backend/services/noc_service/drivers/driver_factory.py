"""
Factory that returns the correct driver for a given device.
"""
from backend.services.noc_service.drivers.base_driver import BaseNetworkDriver
from backend.services.noc_service.drivers.cisco_driver import CiscoDriver
from backend.services.noc_service.drivers.mikrotik_driver import MikrotikDriver
from backend.services.noc_service.drivers.generic_ssh_driver import GenericSSHDriver


VENDOR_DRIVER_MAP: dict[str, type[BaseNetworkDriver]] = {
    "cisco":    CiscoDriver,
    "mikrotik": MikrotikDriver,
}


def get_driver(device) -> BaseNetworkDriver:
    """Get the appropriate driver for a device object."""
    vendor = (device.vendor or "").lower().strip()

    driver_class = VENDOR_DRIVER_MAP.get(vendor, GenericSSHDriver)

    config = {
        "ip_address":    device.ip_address,
        "hostname":      device.hostname,
        "vendor":        device.vendor,
        "model":         device.model,
        "snmp_version":  device.snmp_version,
        "snmp_community": device.snmp_community,
        "snmp_config":   device.snmp_config or {},
        "ssh_config":    device.ssh_config or {},
    }
    return driver_class(config)
