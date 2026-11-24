"""Dependency wiring.

One place that knows how to build the object graph, so handlers receive ready
services and tests can substitute fakes. Lambda containers are reused between
invocations, so the graph is built once per process and cached -- which matters
more than usual at this account's concurrency ceiling of 10 (ADR-0014), where
cold-start work is felt immediately.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from adapters.location import build_location_providers
from adapters.notifications import build_channels
from appcore.auth import Authenticator, CognitoTokenVerifier, LocalTokenVerifier
from appcore.environment import (
    EnvironmentConfigurationError,
    is_local_environment,
    require_local_auth_allowed,
)
from repositories.alert_repo import AlertRepository
from repositories.camp_repo import CampRepository, DonationRepository
from repositories.emergency_repo import EmergencyRepository
from repositories.facility_repo import FacilityRepository
from repositories.identity_repo import IdentityRepository
from repositories.inventory_repo import InventoryRepository
from repositories.platform_repo import (
    AuditRepository,
    IdempotencyRepository,
    NotificationRepository,
    OutboxRepository,
)
from repositories.reservation_repo import ReservationRepository


def is_local() -> bool:
    """Whether local development behaviour is permitted in this process.

    Raises ``EnvironmentConfigurationError`` rather than returning True inside an
    AWS execution environment — see ``appcore/environment.py``.
    """
    return is_local_environment()


@dataclass
class Repositories:
    identity: IdentityRepository
    facilities: FacilityRepository
    inventory: InventoryRepository
    alerts: AlertRepository
    reservations: ReservationRepository
    camps: CampRepository
    donations: DonationRepository
    emergency: EmergencyRepository
    notifications: NotificationRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository
    outbox: OutboxRepository


def build_repositories() -> Repositories:
    return Repositories(
        identity=IdentityRepository(),
        facilities=FacilityRepository(),
        inventory=InventoryRepository(),
        alerts=AlertRepository(),
        reservations=ReservationRepository(),
        camps=CampRepository(),
        donations=DonationRepository(),
        emergency=EmergencyRepository(),
        notifications=NotificationRepository(),
        audit=AuditRepository(),
        idempotency=IdempotencyRepository(),
        outbox=OutboxRepository(),
    )


@dataclass
class Services:
    repos: Repositories
    authenticator: Authenticator
    notifications: object
    inventory: object
    discovery: object
    alerts: object
    reservations: object
    camps: object
    emergency: object
    geocoder: object
    router: object


def _build_authenticator(repos: Repositories) -> Authenticator:
    if is_local():
        from pathlib import Path

        # Explicit refusal, independent of is_local() above. Two checks rather
        # than one because this is the branch that decides whether identities
        # are verified by Cognito or by a keypair on someone's laptop.
        require_local_auth_allowed()

        key_path = Path(os.environ.get("LOCAL_JWT_PUBLIC_KEY", ".local-keys/dev_public.pem"))
        if not key_path.is_file():
            raise EnvironmentConfigurationError(
                f"local mode requires a development public key at {key_path}. "
                "Run 'python scripts/dev.py keys' to generate one."
            )
        verifier = LocalTokenVerifier(public_key_pem=key_path.read_bytes())
    else:
        pool_id = os.environ.get("COGNITO_USER_POOL_ID")
        if not pool_id:
            # Fail closed with a message that says what to do. A bare KeyError
            # here would be a 500 with no explanation, and the one thing worse
            # than refusing to start is refusing to start for no stated reason.
            raise EnvironmentConfigurationError(
                "COGNITO_USER_POOL_ID is required outside local mode: there is no "
                "fallback verifier, by design. Set it to the deployed user pool id."
            )
        verifier = CognitoTokenVerifier(
            region=os.environ.get("AWS_REGION", "ap-southeast-2"),
            user_pool_id=pool_id,
            client_id=os.environ.get("COGNITO_CLIENT_ID"),
        )
    from domain.clock import now_utc

    def provision(*, user_id: str, email: str | None, display_name: str | None):
        """Create a minimal profile for a verified-but-unknown subject.

        A Cognito *access* token carries no email or name claim -- those live
        on the id token, which the API never receives. Without a lookup the
        new profile's display name is the raw subject uuid, which a user sees
        as their own name and reads as broken.

        So the attributes are fetched from the user pool, once, on the single
        request that provisions the account. The API role already holds
        AdminGetUser for exactly this. A failure here is not allowed to block
        sign-in: the profile is still created, just with a plainer name.
        """
        if not email and not is_local():
            try:
                import boto3

                pool_id = os.environ.get("COGNITO_USER_POOL_ID")
                if pool_id:
                    described = boto3.client(
                        "cognito-idp",
                        region_name=os.environ.get("AWS_REGION", "ap-southeast-2"),
                    ).admin_get_user(UserPoolId=pool_id, Username=user_id)
                    attributes = {
                        a["Name"]: a["Value"] for a in described.get("UserAttributes", [])
                    }
                    email = email or attributes.get("email")
                    display_name = display_name or attributes.get("name")
            except Exception:  # noqa: BLE001 - never block sign-in on this
                pass

        return repos.identity.provision_from_token(
            user_id=user_id,
            email=email,
            display_name=display_name,
            now=now_utc(),
        )

    return Authenticator(
        verifier=verifier, directory=repos.identity, provisioner=provision
    )


@lru_cache(maxsize=1)
def get_services() -> Services:
    from .alert_service import AlertService
    from .camp_service import CampService
    from .discovery_service import DiscoveryService
    from .emergency_service import EmergencyService
    from .inventory_service import InventoryService
    from .notification_service import NotificationService

    repos = build_repositories()
    local = is_local()

    channels = build_channels(
        local_mode=local,
        notification_repository=repos.notifications,
        sender_email=os.environ.get("SES_SENDER"),
    )
    notifications = NotificationService(
        channels=channels,
        preferences_repository=repos.notifications,
        identity_repository=repos.identity,
    )
    geocoder, router = build_location_providers(local_mode=local)

    inventory = InventoryService(
        inventory_repository=repos.inventory,
        facility_repository=repos.facilities,
        audit_repository=repos.audit,
        outbox_repository=repos.outbox,
        idempotency_repository=repos.idempotency,
    )
    discovery = DiscoveryService(
        facility_repository=repos.facilities,
        inventory_repository=repos.inventory,
        geocoder=geocoder,
        router=router,
    )
    alerts = AlertService(
        alert_repository=repos.alerts,
        facility_repository=repos.facilities,
        inventory_repository=repos.inventory,
        notification_service=notifications,
        audit_repository=repos.audit,
    )
    from ulid import ULID

    from .reservation_service import ReservationService

    reservations = ReservationService(
        reservation_repository=repos.reservations,
        inventory_repository=repos.inventory,
        facility_repository=repos.facilities,
        audit_repository=repos.audit,
        id_factory=lambda: str(ULID()),
    )
    # Attached after construction: InventoryService needs the reservation
    # service and the reservation service needs the inventory repository, so
    # one of the two links has to be made late. A setter here is simpler and
    # more obvious than a lazy provider or a third coordinating object.
    inventory._reservations = reservations
    discovery._reservations = reservations

    camps = CampService(
        camp_repository=repos.camps,
        donation_repository=repos.donations,
        identity_repository=repos.identity,
        notification_service=notifications,
        audit_repository=repos.audit,
    )
    emergency = EmergencyService(
        emergency_repository=repos.emergency,
        identity_repository=repos.identity,
        facility_repository=repos.facilities,
        inventory_repository=repos.inventory,
        notification_service=notifications,
        audit_repository=repos.audit,
        outbox_repository=repos.outbox,
        idempotency_repository=repos.idempotency,
        discovery_service=discovery,
    )

    return Services(
        repos=repos,
        authenticator=_build_authenticator(repos),
        notifications=notifications,
        inventory=inventory,
        discovery=discovery,
        alerts=alerts,
        reservations=reservations,
        camps=camps,
        emergency=emergency,
        geocoder=geocoder,
        router=router,
    )


def reset_services() -> None:
    """Clear the cached graph. Used by tests between cases."""
    get_services.cache_clear()
