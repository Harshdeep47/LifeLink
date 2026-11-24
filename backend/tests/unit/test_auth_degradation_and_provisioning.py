"""Two P0 defects, and the boundaries their fixes must not cross.

**Defect 1 — a bad token broke every public route.** ``build_context`` raised
on any authentication failure, before ``requires()`` could consider whether the
route tolerates an anonymous caller. So one stale token in a browser tab
returned 401 from blood availability search, the facility list, donation camps
and ``/reference`` — the home page's own reference data. Confirmed against the
deployed API before the fix.

**Defect 2 — a verified Cognito user had no LifeLink account.** Anyone signing
up through the hosted UI got a ``sub`` with no profile, and every request was
refused with "authenticated subject has no LifeLink account". Nothing in the
product could create that profile, so it was a dead end.

Both fixes widen what succeeds, which is exactly when a test file should spend
most of its assertions on what must still fail.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from appcore.auth import Authenticator, build_context, requires
from appcore.context import ANONYMOUS, Principal, RequestContext
from appcore.rbac import Permission, Role
from domain.errors import (
    AccountSuspendedError,
    ForbiddenError,
    UnauthenticatedError,
)

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)


class FailingVerifier:
    """Rejects every token, like an expired or malformed one."""

    def __init__(self, message="token has expired"):
        self.message = message

    def verify(self, token):
        raise UnauthenticatedError(self.message)


class StaticVerifier:
    def __init__(self, claims):
        self.claims = claims

    def verify(self, token):
        return dict(self.claims)


class Directory:
    """In-memory user directory."""

    def __init__(self, principals=None):
        self.principals = dict(principals or {})

    def get_principal(self, user_id):
        return self.principals.get(user_id)


def event_with(token=None):
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return {"headers": headers, "requestContext": {"stage": "dev"}}


# --- Defect 1: public routes survive a bad token ----------------------------


class TestABadTokenDoesNotBreakPublicRoutes:
    def test_context_captures_the_failure_instead_of_raising(self):
        context = build_context(
            event_with("rubbish"),
            Authenticator(verifier=FailingVerifier(), directory=Directory()),
        )
        assert context.principal is ANONYMOUS
        assert isinstance(context.auth_error, UnauthenticatedError)

    def test_a_public_handler_still_runs(self):
        """The regression: this used to 401."""

        @requires(Permission.FACILITY_READ, allow_anonymous=True)
        def public_handler(event, context):
            return {"statusCode": 200, "body": "facilities"}

        context = build_context(
            event_with("expired"),
            Authenticator(verifier=FailingVerifier(), directory=Directory()),
        )
        assert public_handler({}, context)["statusCode"] == 200

    def test_no_header_at_all_still_works(self):
        @requires(Permission.CAMP_READ, allow_anonymous=True)
        def public_handler(event, context):
            return {"statusCode": 200}

        context = build_context(
            event_with(), Authenticator(verifier=FailingVerifier(), directory=Directory())
        )
        assert context.auth_error is None
        assert public_handler({}, context)["statusCode"] == 200


class TestProtectedRoutesStillRefuse:
    """The half of the fix that must not have been weakened."""

    @pytest.mark.parametrize(
        "message",
        ["token has expired", "invalid token: bad padding", "token has no subject claim"],
    )
    def test_a_bad_token_is_refused_with_its_real_reason(self, message):
        @requires(Permission.INVENTORY_WRITE)
        def protected(event, context):  # pragma: no cover - must not run
            raise AssertionError("a protected handler ran with a bad token")

        context = build_context(
            event_with("bad"),
            Authenticator(verifier=FailingVerifier(message), directory=Directory()),
        )
        with pytest.raises(UnauthenticatedError) as excinfo:
            protected({}, context)
        # The original reason survives: "token has expired" tells a client to
        # refresh; "authentication required" does not.
        assert message in str(excinfo.value)

    def test_a_protected_route_with_no_token_is_refused(self):
        @requires(Permission.INVENTORY_WRITE)
        def protected(event, context):  # pragma: no cover
            raise AssertionError("ran without a token")

        context = build_context(event_with(), None)
        with pytest.raises(UnauthenticatedError):
            protected({}, context)

    def test_a_bad_token_cannot_reach_a_public_route_needing_a_permission(self):
        """allow_anonymous only helps where the public role holds the permission."""

        @requires(Permission.INVENTORY_WRITE, allow_anonymous=True)
        def oddly_declared(event, context):  # pragma: no cover
            raise AssertionError("anonymous must not hold inventory:write")

        context = build_context(
            event_with("bad"),
            Authenticator(verifier=FailingVerifier(), directory=Directory()),
        )
        with pytest.raises(ForbiddenError):
            oddly_declared({}, context)


# --- Defect 2: provisioning, and its limits ---------------------------------


class RecordingProvisioner:
    def __init__(self, directory, roles=(Role.DONOR.value,), organization_id=None):
        self.directory = directory
        self.roles = tuple(roles)
        self.organization_id = organization_id
        self.calls = []

    def __call__(self, *, user_id, email, display_name):
        self.calls.append({"user_id": user_id, "email": email, "display_name": display_name})
        self.directory.principals[user_id] = Principal(
            user_id=user_id,
            email=email,
            roles=self.roles,
            organization_id=self.organization_id,
            account_status="ACTIVE",
        )
        return self.directory.principals[user_id]


class TestProvisioningAnUnknownSubject:
    def test_an_unknown_subject_is_provisioned_and_admitted(self):
        directory = Directory()
        provisioner = RecordingProvisioner(directory)
        auth = Authenticator(
            verifier=StaticVerifier(
                {"sub": "new-sub-1", "email": "a@example.invalid", "token_use": "access"}
            ),
            directory=directory,
            provisioner=provisioner,
        )
        principal = auth.authenticate("Bearer good")
        assert principal.user_id == "new-sub-1"
        assert provisioner.calls == [
            {"user_id": "new-sub-1", "email": "a@example.invalid", "display_name": None}
        ]

    def test_the_provisioned_role_is_donor_only(self):
        """The security property: never a privileged role."""
        directory = Directory()
        provisioner = RecordingProvisioner(directory)
        auth = Authenticator(
            verifier=StaticVerifier({"sub": "new-sub-2", "email": "b@example.invalid"}),
            directory=directory,
            provisioner=provisioner,
        )
        principal = auth.authenticate("Bearer good")
        assert principal.roles == (Role.DONOR.value,)

    def test_the_provisioned_account_has_no_organization(self):
        """No org means every organization-scoped check refuses by construction."""
        directory = Directory()
        auth = Authenticator(
            verifier=StaticVerifier({"sub": "new-sub-3"}),
            directory=directory,
            provisioner=RecordingProvisioner(directory),
        )
        assert auth.authenticate("Bearer good").organization_id is None

    @pytest.mark.parametrize(
        "permission",
        [
            Permission.EMERGENCY_CERTIFY_PRIORITY,
            Permission.INVENTORY_WRITE,
            Permission.INVENTORY_VERIFY,
            Permission.RESERVATION_MANAGE,
            Permission.AUDIT_READ,
            Permission.USER_MANAGE,
            Permission.HOSPITAL_VERIFY,
            Permission.DONATION_VERIFY,
        ],
    )
    def test_a_provisioned_account_holds_no_privileged_permission(self, permission):
        directory = Directory()
        auth = Authenticator(
            verifier=StaticVerifier({"sub": "new-sub-4"}),
            directory=directory,
            provisioner=RecordingProvisioner(directory),
        )
        assert auth.authenticate("Bearer good").has(permission) is False

    def test_a_provisioned_account_can_do_donor_things(self):
        directory = Directory()
        auth = Authenticator(
            verifier=StaticVerifier({"sub": "new-sub-5"}),
            directory=directory,
            provisioner=RecordingProvisioner(directory),
        )
        principal = auth.authenticate("Bearer good")
        assert principal.has(Permission.RESERVATION_CREATE) is True
        assert principal.has(Permission.REGISTRATION_CREATE) is True

    def test_an_existing_user_is_not_reprovisioned(self):
        """Provisioning must never overwrite a real profile and its roles."""
        existing = Principal(
            user_id="known-sub",
            email="staff@example.invalid",
            roles=("BLOOD_BANK_ADMIN",),
            organization_id="org-1",
            account_status="ACTIVE",
        )
        directory = Directory({"known-sub": existing})
        provisioner = RecordingProvisioner(directory)
        auth = Authenticator(
            verifier=StaticVerifier({"sub": "known-sub"}),
            directory=directory,
            provisioner=provisioner,
        )
        principal = auth.authenticate("Bearer good")
        assert provisioner.calls == [], "an existing profile was re-provisioned"
        assert principal.roles == ("BLOOD_BANK_ADMIN",)
        assert principal.organization_id == "org-1"

    def test_without_a_provisioner_an_unknown_subject_is_still_refused(self):
        """Behaviour is unchanged where provisioning is not configured."""
        auth = Authenticator(
            verifier=StaticVerifier({"sub": "nobody"}),
            directory=Directory(),
            provisioner=None,
        )
        with pytest.raises(UnauthenticatedError) as excinfo:
            auth.authenticate("Bearer good")
        assert "no LifeLink account" in str(excinfo.value)

    def test_a_token_with_no_subject_is_refused_before_provisioning(self):
        directory = Directory()
        provisioner = RecordingProvisioner(directory)
        auth = Authenticator(
            verifier=StaticVerifier({"email": "x@example.invalid"}),
            directory=directory,
            provisioner=provisioner,
        )
        with pytest.raises(UnauthenticatedError):
            auth.authenticate("Bearer good")
        assert provisioner.calls == [], "provisioned without a subject"


class TestSuspensionStillWins:
    """Provisioning must not become a way around suspension."""

    def test_a_suspended_account_is_refused(self):
        suspended = Principal(
            user_id="susp",
            email=None,
            roles=("DONOR",),
            organization_id=None,
            account_status="SUSPENDED",
        )
        directory = Directory({"susp": suspended})
        provisioner = RecordingProvisioner(directory)
        auth = Authenticator(
            verifier=StaticVerifier({"sub": "susp"}),
            directory=directory,
            provisioner=provisioner,
        )
        principal = auth.authenticate("Bearer good")

        @requires(Permission.RESERVATION_CREATE)
        def protected(event, context):  # pragma: no cover
            raise AssertionError("a suspended account acted")

        context = RequestContext(correlation_id="c", principal=principal)
        with pytest.raises(AccountSuspendedError):
            protected({}, context)
        assert provisioner.calls == [], "a suspended user was re-provisioned"
