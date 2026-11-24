"""Request context: who is calling, on behalf of which organization, under which
correlation id.

Built once by the authorization decorator and passed down explicitly. Nothing in
the service layer reads global state to discover the caller, which is what makes
organization isolation reviewable: if a service needs the caller, it is in the
signature.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .rbac import Permission, permissions_for


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, as resolved from the database -- not from token claims.

    Roles come from the stored user record so that a role revoked mid-session
    takes effect on the next request rather than when the token happens to expire.
    """

    user_id: str
    email: str | None
    roles: tuple[str, ...]
    organization_id: str | None
    account_status: str
    display_name: str | None = None

    @property
    def is_active(self) -> bool:
        return self.account_status == "ACTIVE"

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.roles)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


ANONYMOUS = Principal(
    user_id="anonymous",
    email=None,
    roles=("PUBLIC",),
    organization_id=None,
    account_status="ACTIVE",
)


@dataclass(frozen=True, slots=True)
class RequestContext:
    correlation_id: str
    principal: Principal
    source_ip: str | None = None
    user_agent: str | None = None
    idempotency_key: str | None = None
    attributes: dict = field(default_factory=dict)
    #: Why authentication failed, if an Authorization header was present and
    #: unusable. Carried rather than raised so that a public route can still be
    #: served anonymously: a stale token in a browser tab must not break blood
    #: availability search. ``requires()`` raises this for protected routes.
    auth_error: Exception | None = None

    @property
    def actor_id(self) -> str:
        return self.principal.user_id

    @property
    def organization_id(self) -> str | None:
        return self.principal.organization_id

    @property
    def is_authenticated(self) -> bool:
        return self.principal.user_id != "anonymous"


def new_correlation_id() -> str:
    return f"corr-{uuid.uuid4()}"


def anonymous_context(correlation_id: str | None = None) -> RequestContext:
    return RequestContext(
        correlation_id=correlation_id or new_correlation_id(),
        principal=ANONYMOUS,
    )
