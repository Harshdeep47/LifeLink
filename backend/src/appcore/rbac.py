"""Roles, permissions and the authorization matrix (spec 8.2).

Permissions are the unit of authorization, not roles -- handlers declare the
permission they need and never enumerate roles. That keeps the matrix in one
auditable place and makes "which roles can verify a donation?" a question with a
single answer rather than a grep.

Organization scoping is orthogonal: holding a permission is necessary but not
sufficient: the resource must also belong to the caller's organization unless the
permission is explicitly global.
"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    PUBLIC = "PUBLIC"
    DONOR = "DONOR"
    BLOOD_BANK_ADMIN = "BLOOD_BANK_ADMIN"
    BLOOD_BANK_STAFF = "BLOOD_BANK_STAFF"
    HOSPITAL_ADMIN = "HOSPITAL_ADMIN"
    HOSPITAL_STAFF = "HOSPITAL_STAFF"
    HOSPITAL_AUTHORIZER = "HOSPITAL_AUTHORIZER"
    CAMP_ORGANIZER = "CAMP_ORGANIZER"
    CAMP_STAFF = "CAMP_STAFF"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"


class Permission(StrEnum):
    # --- Inventory (Feature 1) ---
    INVENTORY_READ_PUBLIC = "inventory:read:public"
    INVENTORY_READ_DETAILED = "inventory:read:detailed"
    INVENTORY_WRITE = "inventory:write"
    INVENTORY_CORRECT = "inventory:correct"
    INVENTORY_QUARANTINE = "inventory:quarantine"
    INVENTORY_VERIFY = "inventory:verify"
    INVENTORY_INGEST_API = "inventory:ingest:api"

    # --- Alerts (Feature 1 submodule) ---
    ALERT_CREATE = "alert:create"
    ALERT_MANAGE_OWN = "alert:manage:own"
    # Temporary reservations. RESERVATION_CREATE and RESERVATION_MANAGE_OWN are
    # the requester's side; RESERVATION_MANAGE is facility staff deciding on
    # requests against their own stock.
    RESERVATION_CREATE = "reservation:create"
    RESERVATION_MANAGE_OWN = "reservation:manage:own"
    RESERVATION_MANAGE = "reservation:manage"
    # Every signed-in user can read and edit their *own* profile, whatever
    # their role. /me previously required registration:manage:own -- a donor
    # permission -- so a blood bank administrator got 403 viewing their own
    # account. Separate from the donor registration permissions because
    # "see my own name" is not a donor capability.
    PROFILE_MANAGE_OWN = "profile:manage:own"

    # --- Facilities (Feature 2) ---
    FACILITY_READ = "facility:read"
    FACILITY_WRITE = "facility:write"
    FACILITY_VERIFY = "facility:verify"

    # --- Camps (Feature 3) ---
    CAMP_READ = "camp:read"
    CAMP_CREATE = "camp:create"
    CAMP_MANAGE = "camp:manage"
    CAMP_APPROVE = "camp:approve"
    CAMP_STAFF_ASSIGN = "camp:staff:assign"
    CAMP_CHECKIN = "camp:checkin"
    DONATION_RECORD = "donation:record"
    DONATION_VERIFY = "donation:verify"
    REGISTRATION_CREATE = "registration:create"
    REGISTRATION_MANAGE_OWN = "registration:manage:own"

    # --- Emergency (Feature 4) ---
    EMERGENCY_CREATE = "emergency:create"
    EMERGENCY_READ_OWN = "emergency:read:own"
    EMERGENCY_CERTIFY_PRIORITY = "emergency:certify:priority"
    EMERGENCY_RESPOND = "emergency:respond"
    EMERGENCY_CANCEL = "emergency:cancel"

    # --- Platform / admin (Feature 6) ---
    ORG_READ = "org:read"
    ORG_APPROVE = "org:approve"
    ORG_SUSPEND = "org:suspend"
    HOSPITAL_VERIFY = "hospital:verify"
    USER_MANAGE = "user:manage"
    ROLE_ASSIGN = "role:assign"
    AUDIT_READ = "audit:read"
    SYSTEM_ADMIN = "system:admin"


# Permissions that are inherently global -- they are not scoped to one organization.
GLOBAL_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.INVENTORY_READ_PUBLIC,
    Permission.FACILITY_READ,
    Permission.CAMP_READ,
    Permission.ALERT_CREATE,
    Permission.RESERVATION_CREATE,
    Permission.PROFILE_MANAGE_OWN,
    Permission.REGISTRATION_CREATE,
    Permission.EMERGENCY_CREATE,
    Permission.ORG_APPROVE,
    Permission.ORG_SUSPEND,
    Permission.HOSPITAL_VERIFY,
    Permission.FACILITY_VERIFY,
    Permission.CAMP_APPROVE,
    Permission.USER_MANAGE,
    Permission.ROLE_ASSIGN,
    Permission.AUDIT_READ,
    Permission.SYSTEM_ADMIN,
})


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.PUBLIC: frozenset({
        Permission.INVENTORY_READ_PUBLIC,
        Permission.FACILITY_READ,
        Permission.CAMP_READ,
        # A member of the public may raise an emergency request. The
        # specification contemplates this directly -- "a public user cannot
        # self-declare a hospital as verified" (6.3) is a constraint on
        # certification, not on asking for help -- and VERIFICATION_PENDING
        # exists in the lifecycle (6.8) precisely for a request that no
        # verified hospital has vouched for yet.
        #
        # What this does NOT grant, and must never grant:
        # EMERGENCY_CERTIFY_PRIORITY. A public request carries no clinical
        # priority until an authorized clinician at a currently-verified
        # hospital certifies it.
        Permission.EMERGENCY_CREATE,
    }),
    Role.DONOR: frozenset({
        Permission.PROFILE_MANAGE_OWN,
        Permission.INVENTORY_READ_PUBLIC,
        Permission.FACILITY_READ,
        Permission.CAMP_READ,
        Permission.ALERT_CREATE,
        Permission.ALERT_MANAGE_OWN,
        Permission.RESERVATION_CREATE,
        Permission.RESERVATION_MANAGE_OWN,
        Permission.REGISTRATION_CREATE,
        Permission.REGISTRATION_MANAGE_OWN,
        Permission.EMERGENCY_CREATE,
        Permission.EMERGENCY_READ_OWN,
        Permission.EMERGENCY_CANCEL,
    }),
    Role.BLOOD_BANK_STAFF: frozenset({
        Permission.PROFILE_MANAGE_OWN,
        Permission.INVENTORY_READ_PUBLIC,
        Permission.INVENTORY_READ_DETAILED,
        Permission.INVENTORY_WRITE,
        Permission.INVENTORY_QUARANTINE,
        Permission.FACILITY_READ,
        Permission.CAMP_READ,
        Permission.EMERGENCY_RESPOND,
        Permission.RESERVATION_MANAGE,
    }),
    Role.BLOOD_BANK_ADMIN: frozenset({
        Permission.PROFILE_MANAGE_OWN,
        Permission.INVENTORY_READ_PUBLIC,
        Permission.INVENTORY_READ_DETAILED,
        Permission.INVENTORY_WRITE,
        Permission.INVENTORY_CORRECT,
        Permission.INVENTORY_QUARANTINE,
        Permission.INVENTORY_VERIFY,
        Permission.INVENTORY_INGEST_API,
        Permission.RESERVATION_MANAGE,
        Permission.FACILITY_READ,
        Permission.FACILITY_WRITE,
        Permission.CAMP_READ,
        Permission.EMERGENCY_RESPOND,
    }),
    Role.HOSPITAL_STAFF: frozenset({
        Permission.PROFILE_MANAGE_OWN,
        Permission.INVENTORY_READ_PUBLIC,
        Permission.INVENTORY_READ_DETAILED,
        Permission.FACILITY_READ,
        Permission.CAMP_READ,
        Permission.EMERGENCY_CREATE,
        Permission.EMERGENCY_READ_OWN,
        Permission.EMERGENCY_CANCEL,
    }),
    Role.HOSPITAL_AUTHORIZER: frozenset({
        Permission.PROFILE_MANAGE_OWN,
        Permission.INVENTORY_READ_PUBLIC,
        Permission.INVENTORY_READ_DETAILED,
        Permission.FACILITY_READ,
        Permission.CAMP_READ,
        Permission.EMERGENCY_CREATE,
        Permission.EMERGENCY_READ_OWN,
        Permission.EMERGENCY_CANCEL,
        # The defining capability of this role, and of no other non-admin role.
        Permission.EMERGENCY_CERTIFY_PRIORITY,
    }),
    Role.HOSPITAL_ADMIN: frozenset({
        Permission.PROFILE_MANAGE_OWN,
        Permission.INVENTORY_READ_PUBLIC,
        Permission.INVENTORY_READ_DETAILED,
        Permission.FACILITY_READ,
        Permission.CAMP_READ,
        Permission.EMERGENCY_CREATE,
        Permission.EMERGENCY_READ_OWN,
        Permission.EMERGENCY_CANCEL,
        Permission.EMERGENCY_CERTIFY_PRIORITY,
        Permission.USER_MANAGE,  # within their own organization only
    }),
    Role.CAMP_STAFF: frozenset({
        Permission.PROFILE_MANAGE_OWN,
        Permission.FACILITY_READ,
        Permission.CAMP_READ,
        Permission.CAMP_CHECKIN,
        Permission.DONATION_RECORD,
        Permission.DONATION_VERIFY,
    }),
    Role.CAMP_ORGANIZER: frozenset({
        Permission.PROFILE_MANAGE_OWN,
        Permission.FACILITY_READ,
        Permission.CAMP_READ,
        Permission.CAMP_CREATE,
        Permission.CAMP_MANAGE,
        Permission.CAMP_STAFF_ASSIGN,
        Permission.CAMP_CHECKIN,
        Permission.DONATION_RECORD,
        Permission.DONATION_VERIFY,
        # Deliberately NOT inventory permissions -- spec 5.7 is explicit that a
        # camp organizer does not thereby gain blood bank inventory rights.
    }),
    Role.PLATFORM_ADMIN: frozenset(Permission),
}


def permissions_for(roles: list[str] | set[str] | tuple[str, ...]) -> frozenset[Permission]:
    """Union of permissions across all of a user's roles."""
    granted: set[Permission] = set()
    for raw in roles:
        try:
            role = Role(raw)
        except ValueError:
            continue  # unknown role grants nothing
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)


def has_permission(roles, permission: Permission) -> bool:
    return permission in permissions_for(roles)


def is_organization_scoped(permission: Permission) -> bool:
    return permission not in GLOBAL_PERMISSIONS
