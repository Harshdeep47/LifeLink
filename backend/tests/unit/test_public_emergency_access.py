"""What an unauthenticated caller may and may not do.

Someone seeking blood in an emergency must not be asked to create an account
first, and the specification contemplates exactly that: VERIFICATION_PENDING
exists in the request lifecycle (6.8) for a request no verified hospital has
vouched for, and the stated constraint is that "a public user cannot
self-declare a hospital as verified" (6.3) — a limit on certification, not on
asking.

So this file asserts one permission and denies many. The denials are the point:
widening public access is exactly the kind of change that can quietly take
other permissions with it, and these tests fail loudly if it does.
"""

from __future__ import annotations

import pytest

from appcore.context import ANONYMOUS
from appcore.rbac import ROLE_PERMISSIONS, Permission, Role


class TestWhatThePublicMayDo:
    @pytest.mark.parametrize(
        "permission",
        [
            Permission.INVENTORY_READ_PUBLIC,
            Permission.FACILITY_READ,
            Permission.CAMP_READ,
            Permission.EMERGENCY_CREATE,
        ],
    )
    def test_granted(self, permission):
        assert ANONYMOUS.has(permission) is True


class TestWhatThePublicMayNotDo:
    """Every one of these would be a serious hole."""

    @pytest.mark.parametrize(
        "permission",
        [
            # The single most important denial: a public caller must never be
            # able to give their own request clinical priority.
            Permission.EMERGENCY_CERTIFY_PRIORITY,
            Permission.EMERGENCY_RESPOND,
            Permission.INVENTORY_WRITE,
            Permission.INVENTORY_VERIFY,
            Permission.INVENTORY_CORRECT,
            Permission.INVENTORY_QUARANTINE,
            Permission.INVENTORY_READ_DETAILED,
            Permission.INVENTORY_INGEST_API,
            Permission.RESERVATION_CREATE,
            Permission.RESERVATION_MANAGE,
            Permission.RESERVATION_MANAGE_OWN,
            Permission.AUDIT_READ,
            Permission.USER_MANAGE,
            Permission.HOSPITAL_VERIFY,
            Permission.FACILITY_VERIFY,
            Permission.CAMP_APPROVE,
            Permission.DONATION_VERIFY,
            Permission.ORG_APPROVE,
            Permission.ORG_SUSPEND,
        ],
    )
    def test_denied(self, permission):
        assert ANONYMOUS.has(permission) is False

    def test_the_public_role_is_small(self):
        """A short allow-list is the control; keep it short.

        If a future change grows this set, that should be a deliberate decision
        made while looking at this assertion, not a side effect.
        """
        granted = ROLE_PERMISSIONS[Role.PUBLIC]
        assert len(granted) == 4, sorted(p.value for p in granted)

    def test_certification_is_not_in_the_public_set(self):
        assert Permission.EMERGENCY_CERTIFY_PRIORITY not in ROLE_PERMISSIONS[Role.PUBLIC]


class TestTheRouteDeclaresItsIntent:
    def test_create_allows_anonymous_and_certify_does_not(self):
        """Read from the route metadata the decorator records.

        Asserting on the wiring rather than on a copy of it: this is the thing
        that actually governs the deployed behaviour.
        """
        from handlers.api import build_router

        router = build_router()
        by_key = {(r.method, r.path): r for r in router.routes}

        create = by_key[("POST", "/emergency-requests")]
        assert create.handler.__lifelink_allows_anonymous__ is True
        assert create.permission is Permission.EMERGENCY_CREATE

        certify = by_key[
            ("POST", "/emergency-requests/{requestId}/certify")
        ]
        assert certify.handler.__lifelink_allows_anonymous__ is False
        assert certify.permission is Permission.EMERGENCY_CERTIFY_PRIORITY

    def test_no_other_route_became_anonymous(self):
        """Only the routes we intend are open.

        A whitelist, because `allow_anonymous=True` on the wrong handler is a
        one-word change with no visible symptom.
        """
        from handlers.api import build_router

        # /health and /reference carry no @requires decorator at all, so they
        # have no metadata to inspect and are not listed here. They expose no
        # data about any person or organization.
        expected_anonymous = {
            ("GET", "/facilities"),
            ("GET", "/facilities/{facilityId}"),
            ("GET", "/facilities/{facilityId}/availability"),
            ("GET", "/facilities/{facilityId}/route"),
            ("GET", "/geocode"),
            ("GET", "/camps"),
            ("GET", "/camps/{campId}"),
            ("POST", "/emergency-requests"),
        }
        actual = {
            (r.method, r.path)
            for r in build_router().routes
            if getattr(r.handler, "__lifelink_allows_anonymous__", False)
        }
        assert actual == expected_anonymous, {
            "unexpectedly public": sorted(actual - expected_anonymous),
            "no longer public": sorted(expected_anonymous - actual),
        }
