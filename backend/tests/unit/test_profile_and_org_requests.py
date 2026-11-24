"""Self-service profile editing must not become role escalation.

Account-type selection is the dangerous part of onboarding: a user picking
"Blood Bank" must be able to *ask*, and must not thereby *become* one. These
tests assert the shape of that boundary.

The attack this file exists to prevent is a single POST:

    PATCH /me  {"displayName": "x", "roles": ["PLATFORM_ADMIN"]}

A generic profile endpoint that merged its body into the stored item would
grant that. The endpoint reads exactly one field instead, and the repository
method names exactly one attribute, so there are two independent reasons the
attack fails.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from appcore.rbac import Permission


def code_without_docstring(function) -> str:
    """Source of a function with its docstring and comments removed.

    Naive substring checks over raw source match the prose that *explains* a
    rule as readily as a violation of it — the first version of these tests
    failed because a docstring said "does not write roles". Comparing against
    the executable body only is the check that actually means something.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    node = tree.body[0]
    body = node.body[1:] if (
        isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ) else node.body
    return chr(10).join(ast.unparse(statement) for statement in body)



def identity_repo_cls():
    """The repository class, imported lazily so collection stays cheap."""
    from repositories.identity_repo import IdentityRepository

    return IdentityRepository


class TestTheProfileEndpointIsNarrow:
    def test_only_display_name_is_read_from_the_body(self):
        """Source-level check, because this is a property of the code's shape.

        If someone later swaps the explicit read for a merge, this fails.
        """
        from handlers import api

        source = inspect.getsource(api.update_my_profile)
        assert 'body.get("displayName")' in source

        for forbidden in ("roles", "organizationId", "accountStatus", "permissions"):
            assert f'body.get("{forbidden}")' not in source, (
                f"update_my_profile reads {forbidden} from the request body"
            )

    def test_it_does_not_splat_the_body(self):
        from handlers import api

        source = inspect.getsource(api.update_my_profile)
        assert "**body" not in source, "the whole body is merged into the update"

    def test_the_repository_writes_only_the_display_name(self):
        code = code_without_docstring(
            identity_repo_cls().update_display_name
        )
        assert "displayName" in code
        for forbidden in ("roles", "organizationId", "accountStatus"):
            assert forbidden not in code, (
                f"update_display_name's expression touches {forbidden}"
            )

    def test_it_requires_an_existing_profile(self):
        """A profile edit must not create an account."""
        code = code_without_docstring(identity_repo_cls().update_display_name)
        assert "exists()" in code


class TestOrganizationRequestsGrantNothing:
    def test_the_request_writes_only_its_own_attribute(self):
        code = code_without_docstring(
            identity_repo_cls().record_organization_request
        )
        assert "pendingOrganizationRequest" in code
        for forbidden in ("roles", "organizationId", "accountStatus"):
            assert forbidden not in code, (
                f"record_organization_request writes {forbidden}"
            )

    def test_the_request_is_stored_as_pending(self):
        code = code_without_docstring(
            identity_repo_cls().record_organization_request
        )
        assert "PENDING" in code

    def test_the_handler_rejects_an_unknown_requested_type(self):
        from handlers import api

        source = inspect.getsource(api.request_organization_access)
        # An allow-list, not a deny-list: anything unrecognised is refused.
        assert "allowed = {" in source
        assert "UNKNOWN_REQUESTED_TYPE" in source

    def test_the_handler_never_assigns_a_role(self):
        from handlers import api

        source = inspect.getsource(api.request_organization_access)
        for forbidden in ("set_account_status", "add_membership", "create_user"):
            assert forbidden not in source, (
                f"request_organization_access calls {forbidden}"
            )

    def test_the_request_is_audited(self):
        from handlers import api

        source = inspect.getsource(api.request_organization_access)
        assert "ORGANIZATION_ACCESS_REQUESTED" in source


class TestTheRoutesUseAnOwnPermission:
    """These endpoints act on the caller's own account only.

    They use PROFILE_MANAGE_OWN, not a donor permission. /me previously
    required registration:manage:own, so a blood bank administrator received
    403 looking at their own profile — a role-shaped permission guarding a
    capability every signed-in user has.
    """

    @pytest.mark.parametrize(
        "method,path",
        [("PATCH", "/me"), ("POST", "/me/organization-request"), ("GET", "/me")],
    )
    def test_declared_permission_is_own_scoped(self, method, path):
        from handlers.api import build_router

        route = {(r.method, r.path): r for r in build_router().routes}[(method, path)]
        assert route.permission is Permission.PROFILE_MANAGE_OWN

    @pytest.mark.parametrize(
        "method,path",
        [("PATCH", "/me"), ("POST", "/me/organization-request")],
    )
    def test_they_are_not_anonymous(self, method, path):
        from handlers.api import build_router

        route = {(r.method, r.path): r for r in build_router().routes}[(method, path)]
        assert getattr(route.handler, "__lifelink_allows_anonymous__", False) is False


class TestAProvisionedDonorCannotEscalate:
    """A freshly provisioned account holds no institutional permission.

    Requesting a type does not change that, because the request writes only
    its own attribute — so there is nothing for these checks to read
    differently afterwards.
    """

    @pytest.mark.parametrize(
        "permission",
        [
            Permission.INVENTORY_WRITE,
            Permission.INVENTORY_VERIFY,
            Permission.RESERVATION_MANAGE,
            Permission.EMERGENCY_CERTIFY_PRIORITY,
            Permission.CAMP_CREATE,
            Permission.DONATION_VERIFY,
            Permission.HOSPITAL_VERIFY,
            Permission.USER_MANAGE,
            Permission.AUDIT_READ,
        ],
    )
    def test_donor_role_lacks_institutional_permissions(self, permission):
        from appcore.rbac import ROLE_PERMISSIONS, Role

        assert permission not in ROLE_PERMISSIONS[Role.DONOR]
