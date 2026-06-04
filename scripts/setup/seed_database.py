"""
Seed the database with initial data:
- Default tenant
- System roles and permissions
- Device types
- Compliance rules (CIS benchmarks)
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.core.database import AsyncSessionLocal, create_all_tables
from backend.shared.models.tenant import Tenant, TenantFeature
from backend.shared.models.user import User, Role, Permission, RolePermission, UserRole
from backend.shared.models.device import DeviceType
from backend.core.security import hash_password
from datetime import datetime, timezone
import uuid


PERMISSIONS = [
    ("devices",        "read"),
    ("devices",        "write"),
    ("devices",        "delete"),
    ("alerts",         "read"),
    ("alerts",         "write"),
    ("incidents",      "read"),
    ("incidents",      "write"),
    ("users",          "read"),
    ("users",          "write"),
    ("roles",          "read"),
    ("roles",          "write"),
    ("configs",        "read"),
    ("configs",        "write"),
    ("compliance",     "read"),
    ("knowledge_base", "read"),
    ("knowledge_base", "write"),
    ("reports",        "read"),
    ("reports",        "write"),
    ("healing",        "read"),
    ("healing",        "approve"),
]

ROLES = {
    "super_admin": PERMISSIONS,
    "tenant_admin": PERMISSIONS,
    "noc_manager": [
        ("devices", "read"), ("devices", "write"),
        ("alerts", "read"), ("alerts", "write"),
        ("incidents", "read"), ("incidents", "write"),
        ("configs", "read"), ("configs", "write"),
        ("healing", "read"), ("healing", "approve"),
        ("reports", "read"),
    ],
    "noc_operator": [
        ("devices", "read"), ("alerts", "read"), ("alerts", "write"),
        ("incidents", "read"), ("configs", "read"),
        ("healing", "read"), ("reports", "read"),
    ],
    "soc_analyst": [
        ("alerts", "read"), ("alerts", "write"),
        ("incidents", "read"), ("incidents", "write"),
        ("knowledge_base", "read"), ("reports", "read"),
        ("healing", "read"),
    ],
    "report_viewer": [
        ("alerts", "read"), ("incidents", "read"),
        ("devices", "read"), ("reports", "read"),
    ],
}

DEVICE_TYPES = [
    {"vendor": "Cisco",    "category": "router",   "os_type": "IOS-XE",    "driver_name": "cisco"},
    {"vendor": "Cisco",    "category": "switch",   "os_type": "IOS-XE",    "driver_name": "cisco"},
    {"vendor": "Cisco",    "category": "firewall",  "os_type": "ASA",       "driver_name": "cisco_asa"},
    {"vendor": "MikroTik", "category": "router",   "os_type": "RouterOS",  "driver_name": "mikrotik"},
    {"vendor": "MikroTik", "category": "switch",   "os_type": "RouterOS",  "driver_name": "mikrotik"},
    {"vendor": "Juniper",  "category": "router",   "os_type": "JunOS",     "driver_name": "generic_ssh"},
    {"vendor": "Fortinet", "category": "firewall",  "os_type": "FortiOS",   "driver_name": "generic_ssh"},
    {"vendor": "Palo Alto","category": "firewall",  "os_type": "PAN-OS",    "driver_name": "generic_ssh"},
    {"vendor": "HP",       "category": "switch",   "os_type": "ProCurve",  "driver_name": "generic_ssh"},
    {"vendor": "Dell",     "category": "switch",   "os_type": "OS10",      "driver_name": "generic_ssh"},
    {"vendor": "Ubiquiti", "category": "ap",       "os_type": "UniFi",     "driver_name": "generic_ssh"},
    {"vendor": "Huawei",   "category": "router",   "os_type": "VRP",       "driver_name": "generic_ssh"},
    {"vendor": "Arista",   "category": "switch",   "os_type": "EOS",       "driver_name": "generic_ssh"},
]


async def seed():
    print("Creating tables...")
    await create_all_tables()

    async with AsyncSessionLocal() as db:
        # ── Permissions ──────────────────────────────────────────────────────
        print("Seeding permissions...")
        perm_map: dict[tuple, Permission] = {}
        for resource, action in PERMISSIONS:
            perm = Permission(resource=resource, action=action)
            db.add(perm)
            perm_map[(resource, action)] = perm
        await db.flush()

        # ── Tenant ───────────────────────────────────────────────────────────
        print("Creating default tenant...")
        tenant = Tenant(
            code="default",
            name="Default Organization",
            schema_name="tenant_default",
            tier="enterprise",
        )
        db.add(tenant)
        await db.flush()

        for feature in ["noc", "soc", "server", "physec", "rag"]:
            db.add(TenantFeature(tenant_id=tenant.id, feature=feature, enabled=True))

        # ── Roles ────────────────────────────────────────────────────────────
        print("Creating roles...")
        role_map: dict[str, Role] = {}
        for role_name, role_perms in ROLES.items():
            role = Role(
                tenant_id=tenant.id,
                name=role_name,
                is_system=True,
                description=f"System role: {role_name.replace('_', ' ').title()}",
            )
            db.add(role)
            await db.flush()
            role_map[role_name] = role

            for resource, action in role_perms:
                key = (resource, action)
                if key in perm_map:
                    db.add(RolePermission(role_id=role.id, permission_id=perm_map[key].id))

        # ── Admin User ───────────────────────────────────────────────────────
        print("Creating admin user (admin / Admin@1234)...")
        admin = User(
            tenant_id=tenant.id,
            username="admin",
            email="admin@aeaop.internal",
            password_hash=hash_password("Admin@1234"),
            full_name="Platform Administrator",
            is_active=True,
        )
        db.add(admin)
        await db.flush()

        db.add(UserRole(
            user_id=admin.id,
            role_id=role_map["super_admin"].id,
            granted_at=datetime.now(timezone.utc),
        ))

        # ── Device Types ─────────────────────────────────────────────────────
        print("Seeding device types...")
        for dt in DEVICE_TYPES:
            db.add(DeviceType(**dt))

        await db.commit()
        print("\n✅ Database seeded successfully!")
        print(f"   Tenant: {tenant.code} ({tenant.name})")
        print(f"   Admin: admin / Admin@1234")
        print(f"   Roles: {len(ROLES)} roles created")
        print(f"   Permissions: {len(PERMISSIONS)} permissions created")
        print(f"   Device types: {len(DEVICE_TYPES)} types created")


if __name__ == "__main__":
    asyncio.run(seed())
