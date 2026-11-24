"""Integration test fixtures.

These run against a real DynamoDB API surface provided by moto in-process: real
condition expressions, real transactions, real GSI behaviour, no network. That
matters because the invariants being tested -- conditional writes, transaction
cancellation, index range queries -- are precisely the things a hand-rolled fake
would get wrong and quietly pass.

Clearly distinguished from unit tests, which touch no AWS surface at all, and
from any test against real AWS, of which there are none in this suite.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

UTC = UTC
NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)

# Set before any boto3 client is constructed.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_REGION", "ap-southeast-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")
os.environ["LIFELINK_ENV"] = "test"
os.environ["LIFELINK_TABLE_PREFIX"] = "lifelink-test"
os.environ.pop("DYNAMODB_ENDPOINT", None)


@pytest.fixture
def aws(monkeypatch):
    """A fresh mocked AWS environment with all LifeLink tables created."""
    from moto import mock_aws

    with mock_aws():
        from repositories.dynamo import Tables, _resource, reset_resource_cache, table_name
        from repositories.schema import create_table_kwargs

        reset_resource_cache()
        client = _resource().meta.client
        for logical in Tables.all():
            client.create_table(**create_table_kwargs(logical, table_name(logical)))

        yield client

        reset_resource_cache()


@pytest.fixture
def repos(aws):
    from services.container import build_repositories

    return build_repositories()


@pytest.fixture
def now():
    return NOW


def hours_ago(h: float, base: datetime = NOW) -> datetime:
    return base - timedelta(hours=h)


def hours_ahead(h: float, base: datetime = NOW) -> datetime:
    return base + timedelta(hours=h)


def days_ahead(d: float, base: datetime = NOW) -> datetime:
    return base + timedelta(days=d)


def days_ago(d: float, base: datetime = NOW) -> datetime:
    return base - timedelta(days=d)


def make_context(
    *,
    user_id: str = "u-1",
    roles: tuple[str, ...] = ("BLOOD_BANK_ADMIN",),
    organization_id: str | None = "org-1",
    status: str = "ACTIVE",
    correlation_id: str = "corr-integration",
    idempotency_key: str | None = None,
):
    from appcore.context import Principal, RequestContext

    return RequestContext(
        correlation_id=correlation_id,
        principal=Principal(
            user_id=user_id,
            email=f"{user_id}@example.test",
            roles=roles,
            organization_id=organization_id,
            account_status=status,
        ),
        idempotency_key=idempotency_key,
    )


class FakeChannel:
    """Records what would have been sent, so notification assertions are precise."""

    def __init__(self, channel):
        from adapters.notifications import DeliveryResult, DeliveryStatus

        self.channel = channel
        self.sent = []
        self._result_cls = DeliveryResult
        self._status = DeliveryStatus

    def send(self, message, *, now):
        self.sent.append(message)
        return self._result_cls(self.channel, self._status.SENT, "captured by test")


@pytest.fixture
def notification_service(repos):
    """A notification service whose channels capture instead of sending."""
    from adapters.notifications import Channel
    from services.notification_service import NotificationService

    channels = {
        Channel.EMAIL: FakeChannel(Channel.EMAIL),
        Channel.IN_APP: FakeChannel(Channel.IN_APP),
    }
    service = NotificationService(
        channels=channels,
        preferences_repository=repos.notifications,
        identity_repository=repos.identity,
    )
    service.test_channels = channels
    return service


@pytest.fixture
def inventory_service(repos):
    from services.inventory_service import InventoryService

    return InventoryService(
        inventory_repository=repos.inventory,
        facility_repository=repos.facilities,
        audit_repository=repos.audit,
        outbox_repository=repos.outbox,
        idempotency_repository=repos.idempotency,
    )


@pytest.fixture
def discovery_service(repos):
    from adapters.location import NullRoutingProvider, StaticGeocodingProvider
    from services.discovery_service import DiscoveryService

    return DiscoveryService(
        facility_repository=repos.facilities,
        inventory_repository=repos.inventory,
        geocoder=StaticGeocodingProvider(),
        router=NullRoutingProvider(),
    )


@pytest.fixture
def alert_service(repos, notification_service):
    from services.alert_service import AlertService

    return AlertService(
        alert_repository=repos.alerts,
        facility_repository=repos.facilities,
        inventory_repository=repos.inventory,
        notification_service=notification_service,
        audit_repository=repos.audit,
    )


@pytest.fixture
def camp_service(repos, notification_service):
    from services.camp_service import CampService

    return CampService(
        camp_repository=repos.camps,
        donation_repository=repos.donations,
        identity_repository=repos.identity,
        notification_service=notification_service,
        audit_repository=repos.audit,
    )


@pytest.fixture
def emergency_service(repos, notification_service, discovery_service):
    from services.emergency_service import EmergencyService

    return EmergencyService(
        emergency_repository=repos.emergency,
        identity_repository=repos.identity,
        facility_repository=repos.facilities,
        inventory_repository=repos.inventory,
        notification_service=notification_service,
        audit_repository=repos.audit,
        outbox_repository=repos.outbox,
        idempotency_repository=repos.idempotency,
        discovery_service=discovery_service,
    )


@pytest.fixture
def seeded(repos, now):
    """A minimal but realistic world: organizations, users, facilities, consent."""
    from repositories.identity_repo import OrganizationStatus, OrganizationType

    repos.identity.create_organization(
        organization_id="org-bb-1", name="Test Blood Bank",
        org_type=OrganizationType.BLOOD_BANK.value,
        status=OrganizationStatus.VERIFIED.value, now=now,
    )
    repos.identity.create_organization(
        organization_id="org-bb-2", name="Other Blood Bank",
        org_type=OrganizationType.BLOOD_BANK.value,
        status=OrganizationStatus.VERIFIED.value, now=now,
    )
    repos.identity.create_organization(
        organization_id="org-hosp-1", name="Test Hospital",
        org_type=OrganizationType.HOSPITAL.value,
        status=OrganizationStatus.VERIFIED.value, now=now,
    )
    repos.identity.create_organization(
        organization_id="org-hosp-susp", name="Suspended Hospital",
        org_type=OrganizationType.HOSPITAL.value,
        status=OrganizationStatus.SUSPENDED.value, now=now,
    )
    repos.identity.create_organization(
        organization_id="org-camp-1", name="Test Camp Organizer",
        org_type=OrganizationType.CAMP_ORGANIZER.value,
        status=OrganizationStatus.VERIFIED.value, now=now,
    )

    users = [
        ("u-bb-admin", ["BLOOD_BANK_ADMIN"], "org-bb-1"),
        ("u-bb-other", ["BLOOD_BANK_ADMIN"], "org-bb-2"),
        ("u-hosp-auth", ["HOSPITAL_AUTHORIZER"], "org-hosp-1"),
        ("u-hosp-staff", ["HOSPITAL_STAFF"], "org-hosp-1"),
        ("u-hosp-susp-auth", ["HOSPITAL_AUTHORIZER"], "org-hosp-susp"),
        ("u-donor-1", ["DONOR"], None),
        ("u-donor-2", ["DONOR"], None),
        ("u-camp-org", ["CAMP_ORGANIZER"], "org-camp-1"),
        ("u-camp-staff", ["CAMP_STAFF"], "org-camp-1"),
        ("u-admin", ["PLATFORM_ADMIN"], None),
    ]
    for user_id, roles, org in users:
        repos.identity.create_user(
            user_id=user_id, email=f"{user_id}@example.test",
            display_name=user_id, roles=roles, organization_id=org, now=now,
        )
        repos.notifications.save_preferences(
            user_id,
            {
                "channels": ["IN_APP", "EMAIL"],
                "consentGiven": True,
                "campNotifications": True,
                "alertNotifications": True,
                "emergencyNotifications": True,
                "notificationRadiusKm": 10,
            },
        )

    # Patiala and a second facility ~2.3 km away.
    repos.facilities.upsert_facility({
        "facilityId": "fac-1", "organizationId": "org-bb-1",
        "name": "Patiala Central", "facilityType": "BLOOD_BANK",
        "address": "1 Test Road", "city": "Patiala", "state": "Punjab",
        "latitude": 30.3398, "longitude": 76.3869,
        "verificationStatus": "VERIFIED", "inventoryKnown": True,
    })
    repos.facilities.upsert_facility({
        "facilityId": "fac-2", "organizationId": "org-bb-2",
        "name": "Patiala East", "facilityType": "BLOOD_BANK",
        "address": "2 Test Road", "city": "Patiala", "state": "Punjab",
        "latitude": 30.3578, "longitude": 76.3749,
        "verificationStatus": "VERIFIED", "inventoryKnown": True,
    })
    # Deliberately never reports inventory, to exercise UNKNOWN.
    repos.facilities.upsert_facility({
        "facilityId": "fac-silent", "organizationId": "org-bb-2",
        "name": "Silent Facility", "facilityType": "BLOOD_BANK",
        "address": "3 Test Road", "city": "Patiala", "state": "Punjab",
        "latitude": 30.3450, "longitude": 76.3900,
        "verificationStatus": "UNVERIFIED", "inventoryKnown": False,
    })
    return repos
