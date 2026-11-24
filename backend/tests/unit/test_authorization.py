"""Authorization: RBAC matrix, suspension, organization isolation, IDOR.

Covers spec 8.1-8.2 and the platform/security edge cases. These are the tests
that would fail loudest if a security boundary regressed.
"""
from __future__ import annotations

import pytest

from appcore.auth import requires
from appcore.context import ANONYMOUS, Principal, RequestContext
from appcore.rbac import (
    GLOBAL_PERMISSIONS,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    has_permission,
    is_organization_scoped,
    permissions_for,
)
from domain.errors import (
    AccountSuspendedError,
    CrossOrganizationError,
    ForbiddenError,
    UnauthenticatedError,
)

pytestmark = pytest.mark.unit


def principal(
    *,
    user_id: str = "u-1",
    roles: tuple[str, ...] = (Role.DONOR,),
    organization_id: str | None = None,
    status: str = "ACTIVE",
) -> Principal:
    return Principal(
        user_id=user_id,
        email="user@example.test",
        roles=roles,
        organization_id=organization_id,
        account_status=status,
    )


def ctx(p: Principal) -> RequestContext:
    return RequestContext(correlation_id="corr-test", principal=p)


class TestRoleMatrix:
    def test_platform_admin_has_every_permission(self):
        assert permissions_for([Role.PLATFORM_ADMIN]) == frozenset(Permission)

    def test_public_role_cannot_write_inventory(self):
        assert has_permission([Role.PUBLIC], Permission.INVENTORY_WRITE) is False

    def test_donor_cannot_write_inventory(self):
        assert has_permission([Role.DONOR], Permission.INVENTORY_WRITE) is False

    def test_camp_organizer_does_not_get_inventory_rights(self):
        """Spec 5.7 is explicit: organising camps grants no blood bank rights."""
        for perm in (
            Permission.INVENTORY_WRITE,
            Permission.INVENTORY_CORRECT,
            Permission.INVENTORY_VERIFY,
            Permission.INVENTORY_QUARANTINE,
        ):
            assert has_permission([Role.CAMP_ORGANIZER], perm) is False, perm

    def test_only_authorizer_roles_may_certify_priority(self):
        """Spec 6.4: only authorized hospital personnel certify clinical priority."""
        allowed = {
            role
            for role, perms in ROLE_PERMISSIONS.items()
            if Permission.EMERGENCY_CERTIFY_PRIORITY in perms
        }
        assert allowed == {
            Role.HOSPITAL_AUTHORIZER,
            Role.HOSPITAL_ADMIN,
            Role.PLATFORM_ADMIN,
        }

    def test_hospital_staff_cannot_certify_priority(self):
        assert has_permission(
            [Role.HOSPITAL_STAFF], Permission.EMERGENCY_CERTIFY_PRIORITY
        ) is False

    def test_only_admin_may_verify_hospitals(self):
        """Spec 6.3: a public user cannot self-declare a hospital verified."""
        allowed = {
            role
            for role, perms in ROLE_PERMISSIONS.items()
            if Permission.HOSPITAL_VERIFY in perms
        }
        assert allowed == {Role.PLATFORM_ADMIN}

    def test_donation_verification_is_limited_to_camp_roles(self):
        allowed = {
            role
            for role, perms in ROLE_PERMISSIONS.items()
            if Permission.DONATION_VERIFY in perms
        }
        assert allowed == {Role.CAMP_STAFF, Role.CAMP_ORGANIZER, Role.PLATFORM_ADMIN}

    def test_donor_cannot_verify_donations(self):
        assert has_permission([Role.DONOR], Permission.DONATION_VERIFY) is False

    def test_multiple_roles_union_their_permissions(self):
        combined = permissions_for([Role.DONOR, Role.CAMP_STAFF])
        assert Permission.REGISTRATION_CREATE in combined
        assert Permission.DONATION_VERIFY in combined

    def test_unknown_role_grants_nothing(self):
        assert permissions_for(["WIZARD"]) == frozenset()

    def test_unknown_role_does_not_dilute_known_roles(self):
        assert permissions_for(["WIZARD", Role.DONOR]) == permissions_for([Role.DONOR])


class TestOrganizationScoping:
    def test_inventory_write_is_organization_scoped(self):
        assert is_organization_scoped(Permission.INVENTORY_WRITE) is True

    def test_public_reads_are_global(self):
        assert is_organization_scoped(Permission.FACILITY_READ) is False
        assert is_organization_scoped(Permission.INVENTORY_READ_PUBLIC) is False

    def test_platform_wide_admin_actions_are_global(self):
        for perm in (Permission.HOSPITAL_VERIFY, Permission.ORG_APPROVE, Permission.AUDIT_READ):
            assert perm in GLOBAL_PERMISSIONS


@requires(Permission.INVENTORY_WRITE, resource_owner=lambda e, c: e.get("ownerOrg"))
def _write_inventory(event, context):
    return {"ok": True}


@requires(Permission.INVENTORY_READ_PUBLIC, allow_anonymous=True)
def _public_read(event, context):
    return {"ok": True}


@requires(Permission.EMERGENCY_CERTIFY_PRIORITY, resource_owner=lambda e, c: e.get("ownerOrg"))
def _certify(event, context):
    return {"ok": True}


class TestRequiresDecorator:
    def test_authorized_caller_passes(self):
        p = principal(roles=(Role.BLOOD_BANK_ADMIN,), organization_id="org-1")
        assert _write_inventory({"ownerOrg": "org-1"}, ctx(p)) == {"ok": True}

    def test_anonymous_is_rejected_on_protected_route(self):
        with pytest.raises(UnauthenticatedError):
            _write_inventory({"ownerOrg": "org-1"}, ctx(ANONYMOUS))

    def test_anonymous_allowed_on_public_route(self):
        assert _public_read({}, ctx(ANONYMOUS)) == {"ok": True}

    def test_wrong_role_is_forbidden(self):
        p = principal(roles=(Role.DONOR,), organization_id="org-1")
        with pytest.raises(ForbiddenError) as exc:
            _write_inventory({"ownerOrg": "org-1"}, ctx(p))
        assert exc.value.details["required"] == Permission.INVENTORY_WRITE.value

    def test_suspended_account_is_blocked_despite_valid_token_and_role(self):
        """Spec 8.1: a valid JWT must not allow a suspended user to act.

        The role is correct and the organization matches -- only the account
        status differs, which is precisely the case that a token-only check
        would wave through.
        """
        p = principal(
            roles=(Role.BLOOD_BANK_ADMIN,), organization_id="org-1", status="SUSPENDED"
        )
        with pytest.raises(AccountSuspendedError):
            _write_inventory({"ownerOrg": "org-1"}, ctx(p))

    def test_suspension_is_checked_before_permission(self):
        """A suspended admin gets ACCOUNT_SUSPENDED, not a misleading FORBIDDEN."""
        p = principal(roles=(Role.DONOR,), organization_id="org-1", status="SUSPENDED")
        with pytest.raises(AccountSuspendedError):
            _write_inventory({"ownerOrg": "org-1"}, ctx(p))

    def test_cross_organization_access_is_denied(self):
        """The IDOR defence: right role, right permission, wrong organization."""
        p = principal(roles=(Role.BLOOD_BANK_ADMIN,), organization_id="org-1")
        with pytest.raises(CrossOrganizationError):
            _write_inventory({"ownerOrg": "org-2"}, ctx(p))

    def test_cross_organization_error_does_not_leak_owner(self):
        p = principal(roles=(Role.BLOOD_BANK_ADMIN,), organization_id="org-1")
        with pytest.raises(CrossOrganizationError) as exc:
            _write_inventory({"ownerOrg": "org-secret"}, ctx(p))
        assert "org-secret" not in str(exc.value)
        assert "org-secret" not in str(exc.value.details)

    def test_user_without_organization_cannot_touch_scoped_resource(self):
        p = principal(roles=(Role.BLOOD_BANK_ADMIN,), organization_id=None)
        with pytest.raises(CrossOrganizationError):
            _write_inventory({"ownerOrg": "org-1"}, ctx(p))

    def test_hospital_staff_cannot_certify_priority_through_the_decorator(self):
        p = principal(roles=(Role.HOSPITAL_STAFF,), organization_id="hosp-1")
        with pytest.raises(ForbiddenError):
            _certify({"ownerOrg": "hosp-1"}, ctx(p))

    def test_authorizer_can_certify_for_own_hospital(self):
        p = principal(roles=(Role.HOSPITAL_AUTHORIZER,), organization_id="hosp-1")
        assert _certify({"ownerOrg": "hosp-1"}, ctx(p)) == {"ok": True}

    def test_authorizer_cannot_certify_for_another_hospital(self):
        p = principal(roles=(Role.HOSPITAL_AUTHORIZER,), organization_id="hosp-1")
        with pytest.raises(CrossOrganizationError):
            _certify({"ownerOrg": "hosp-2"}, ctx(p))

    def test_decorator_marks_the_handler_as_protected(self):
        """Used by the route audit test to prove no endpoint is left undecorated."""
        assert getattr(_write_inventory, "__lifelink_protected__", False) is True
        assert _write_inventory.__lifelink_permission__ is Permission.INVENTORY_WRITE

    def test_platform_admin_bypasses_role_check_but_not_org_check(self):
        """Even a platform admin is subject to the scoping rule on scoped permissions.

        This is deliberate: it keeps the audit trail honest about which
        organization an action was taken against.
        """
        p = principal(roles=(Role.PLATFORM_ADMIN,), organization_id="org-1")
        assert _write_inventory({"ownerOrg": "org-1"}, ctx(p)) == {"ok": True}
        with pytest.raises(CrossOrganizationError):
            _write_inventory({"ownerOrg": "org-9"}, ctx(p))


class TestPrincipalBehaviour:
    def test_active_principal_is_active(self):
        assert principal().is_active is True

    def test_suspended_principal_is_not_active(self):
        assert principal(status="SUSPENDED").is_active is False

    def test_anonymous_principal_has_only_public_permissions(self):
        assert ANONYMOUS.permissions == ROLE_PERMISSIONS[Role.PUBLIC]

    def test_context_exposes_actor_and_organization(self):
        p = principal(user_id="u-9", organization_id="org-3")
        context = ctx(p)
        assert context.actor_id == "u-9"
        assert context.organization_id == "org-3"
        assert context.is_authenticated is True
