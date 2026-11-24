"""Users, organizations and membership -- the source of truth for authorization.

ADR-0007: roles and account status are read from here on every request, never
taken from token claims. That is what makes "suspend this account" and "revoke
this role" take effect immediately rather than whenever a token happens to expire.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from boto3.dynamodb.conditions import Attr, Key

from appcore.context import Principal
from appcore.rbac import Role
from domain.clock import to_iso

from .dynamo import DynamoRepository, Tables


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING = "PENDING"
    CLOSED = "CLOSED"


class OrganizationType(StrEnum):
    BLOOD_BANK = "BLOOD_BANK"
    HOSPITAL = "HOSPITAL"
    CAMP_ORGANIZER = "CAMP_ORGANIZER"


class OrganizationStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class IdentityRepository(DynamoRepository):
    logical_table = Tables.ORGANIZATIONS

    # --- users ---

    def get_user(self, user_id: str) -> dict | None:
        return self.get(f"USER#{user_id}", "PROFILE")

    def get_principal(self, user_id: str) -> Principal | None:
        """Implements the UserDirectory protocol used by the authenticator."""
        item = self.get_user(user_id)
        if item is None:
            return None
        return Principal(
            user_id=item["userId"],
            email=item.get("email"),
            roles=tuple(item.get("roles", [])),
            organization_id=item.get("organizationId"),
            account_status=item.get("accountStatus", AccountStatus.ACTIVE.value),
            display_name=item.get("displayName"),
        )

    def create_user(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        roles: list[str],
        organization_id: str | None,
        now: datetime,
        account_status: str = AccountStatus.ACTIVE.value,
        extra: dict | None = None,
    ) -> dict:
        item = {
            "PK": f"USER#{user_id}",
            "SK": "PROFILE",
            "entityType": "USER",
            "userId": user_id,
            "email": email,
            "displayName": display_name,
            "roles": roles,
            "organizationId": organization_id,
            "accountStatus": account_status,
            "createdAt": to_iso(now),
            "updatedAt": to_iso(now),
            **(extra or {}),
        }
        self.put(item, condition=Attr("PK").not_exists())
        if organization_id:
            self.add_membership(
                organization_id=organization_id, user_id=user_id, roles=roles, now=now
            )
        return item

    def provision_from_token(
        self,
        *,
        user_id: str,
        email: str | None,
        display_name: str | None,
        now: datetime,
    ) -> dict:
        """Create a minimal LifeLink profile for a newly authenticated subject.

        Why this exists. A Cognito user pool can create accounts that LifeLink
        has never seen: anyone who signs up through the hosted UI gets a
        ``sub`` with no corresponding profile here. The authorizer then refused
        every request with "authenticated subject has no LifeLink account" --
        a dead end, because nothing in the product could create that profile.

        What it grants, and what it must never grant. The new profile gets
        exactly one role, ``DONOR``, and **no organization**. That is
        deliberate and is the security property of this method:

        *   A hospital or blood bank role would give access to other
            organizations' data, so those are never self-assigned. They are
            granted by an administrator after verification, through the
            existing approval path.
        *   No organization means every organization-scoped permission check
            refuses by construction, not by convention.

        Idempotent by condition, not by check-then-write: the put is guarded by
        ``attribute_not_exists``, so two concurrent first requests from the
        same new user cannot create two profiles or overwrite one.
        """
        from domain.errors import DuplicateError

        try:
            return self.create_user(
                user_id=user_id,
                email=email or "",
                display_name=display_name or (email.split("@")[0] if email else user_id),
                # Least privilege. Never a privileged role, never an org.
                roles=[Role.DONOR.value],
                organization_id=None,
                now=now,
                account_status=AccountStatus.ACTIVE.value,
                extra={
                    "provisionedFrom": "COGNITO_TOKEN",
                    "provisionedAt": to_iso(now),
                },
            )
        except DuplicateError:
            # Another request for the same new subject won the race. Its
            # profile is as good as the one we were about to write.
            existing = self.get_user(user_id)
            if existing is None:  # pragma: no cover - would mean a vanished write
                raise
            return existing

    def update_display_name(self, *, user_id: str, display_name: str, now: datetime) -> dict:
        """Change only the display name.

        A single named attribute rather than a generic merge, so this cannot
        become a path to writing roles, organizationId or accountStatus. The
        condition keeps it from creating a profile that does not exist.
        """
        return self.update(
            pk=f"USER#{user_id}",
            sk="PROFILE",
            update_expression="SET displayName = :name, updatedAt = :now",
            expression_values={":name": display_name, ":now": to_iso(now)},
            condition=Attr("PK").exists(),
        )

    def record_organization_request(
        self,
        *,
        user_id: str,
        requested_type: str,
        organization_name: str,
        contact_detail: str | None,
        note: str | None,
        now: datetime,
    ) -> dict:
        """Store a PENDING institutional access request.

        Writes to its own attribute and touches nothing else. In particular it
        does not write ``roles``, ``organizationId`` or ``accountStatus``: a
        request is a request, and the account's access is unchanged until an
        administrator verifies it. That separation is the security property
        here, so the update expression names exactly one attribute.
        """
        request = {
            "requestedType": requested_type,
            "organizationName": organization_name,
            "contactDetail": contact_detail,
            "note": note,
            "status": "PENDING",
            "requestedAt": to_iso(now),
        }
        self.update(
            pk=f"USER#{user_id}",
            sk="PROFILE",
            update_expression=(
                "SET pendingOrganizationRequest = :request, updatedAt = :now"
            ),
            expression_values={":request": request, ":now": to_iso(now)},
            condition=Attr("PK").exists(),
        )
        return request

    def set_account_status(self, user_id: str, *, status: str, actor_id: str,
                           now: datetime) -> dict:
        """Suspending an account takes effect on the caller's next request."""
        return self.update(
            pk=f"USER#{user_id}",
            sk="PROFILE",
            update_expression=(
                "SET accountStatus = :s, statusChangedBy = :by, statusChangedAt = :at, "
                "updatedAt = :at"
            ),
            expression_values={":s": status, ":by": actor_id, ":at": to_iso(now)},
            condition=Attr("PK").exists(),
        )

    def set_roles(self, user_id: str, *, roles: list[str], actor_id: str,
                  now: datetime) -> dict:
        return self.update(
            pk=f"USER#{user_id}",
            sk="PROFILE",
            update_expression=(
                "SET #r = :roles, rolesChangedBy = :by, rolesChangedAt = :at, updatedAt = :at"
            ),
            expression_values={":roles": roles, ":by": actor_id, ":at": to_iso(now)},
            expression_names={"#r": "roles"},
            condition=Attr("PK").exists(),
        )

    # --- organizations ---

    def get_organization(self, organization_id: str) -> dict | None:
        return self.get(f"ORG#{organization_id}", "META")

    def create_organization(
        self,
        *,
        organization_id: str,
        name: str,
        org_type: str,
        now: datetime,
        status: str = OrganizationStatus.PENDING_VERIFICATION.value,
        extra: dict | None = None,
    ) -> dict:
        item = {
            "PK": f"ORG#{organization_id}",
            "SK": "META",
            "GSI1PK": f"ORGSTATUS#{status}",
            "GSI1SK": f"ORG#{organization_id}",
            "entityType": "ORGANIZATION",
            "organizationId": organization_id,
            "name": name,
            "organizationType": org_type,
            "status": status,
            "createdAt": to_iso(now),
            **(extra or {}),
        }
        self.put(item, condition=Attr("PK").not_exists())
        return item

    def set_organization_status(
        self, organization_id: str, *, status: str, actor_id: str, now: datetime,
        reason: str | None = None
    ) -> dict:
        """Hospital verification and suspension both run through here.

        Spec 6.3 requires that a suspended hospital loses privileged capability;
        because services recheck this on every sensitive operation, suspension is
        effective immediately rather than at the next login.
        """
        return self.update(
            pk=f"ORG#{organization_id}",
            sk="META",
            update_expression=(
                "SET #s = :s, GSI1PK = :gsi, statusChangedBy = :by, "
                "statusChangedAt = :at, statusReason = :reason"
            ),
            expression_values={
                ":s": status,
                ":gsi": f"ORGSTATUS#{status}",
                ":by": actor_id,
                ":at": to_iso(now),
                ":reason": reason,
            },
            expression_names={"#s": "status"},
            condition=Attr("PK").exists(),
        )

    def list_by_status(self, status: str) -> list[dict]:
        return self.query_all(
            key_condition=Key("GSI1PK").eq(f"ORGSTATUS#{status}"),
            index_name="GSI1-status",
        )

    # --- membership ---

    def add_membership(self, *, organization_id: str, user_id: str, roles: list[str],
                       now: datetime) -> dict:
        item = {
            "PK": f"ORG#{organization_id}",
            "SK": f"MEMBER#{user_id}",
            "entityType": "MEMBERSHIP",
            "organizationId": organization_id,
            "userId": user_id,
            "roles": roles,
            "joinedAt": to_iso(now),
        }
        self.put(item)
        return item

    def list_members(self, organization_id: str) -> list[dict]:
        items, _ = self.query_partition(f"ORG#{organization_id}", sk_prefix="MEMBER#")
        return items

    def is_member(self, organization_id: str, user_id: str) -> bool:
        return self.get(f"ORG#{organization_id}", f"MEMBER#{user_id}") is not None

    def is_hospital_verified(self, organization_id: str) -> bool:
        """Rechecked during sensitive operations, not cached from request start."""
        org = self.get_organization(organization_id)
        if org is None:
            return False
        return (
            org.get("organizationType") == OrganizationType.HOSPITAL.value
            and org.get("status") == OrganizationStatus.VERIFIED.value
        )
