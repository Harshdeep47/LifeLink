"""Authentication and authorization (spec 8.1, 8.2 -- ADR-0007).

Every protected handler is wrapped by ``@requires(...)``. Nothing else performs
authorization, so the rules live in one reviewable place and a route that forgets
to declare its permission fails a test rather than silently going public.

Order of checks matters and is deliberate:

1. Token signature and standard claims.
2. Load the user *from the database* -- roles come from stored state, not claims,
   so a revoked role takes effect on the next request.
3. Account status: a valid JWT from a suspended account is rejected here.
4. Permission check.
5. Organization scoping -- the IDOR defence, applied centrally.
"""
from __future__ import annotations

import functools
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

from domain.errors import (
    AccountSuspendedError,
    CrossOrganizationError,
    ForbiddenError,
    LifeLinkError,
    UnauthenticatedError,
)

from .context import ANONYMOUS, Principal, RequestContext, new_correlation_id
from .environment import (
    EnvironmentConfigurationError,
    environment_name,
    in_aws_execution_environment,
    is_local_environment,
)
from .rbac import Permission, is_organization_scoped


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict:
        """Return validated claims, or raise UnauthenticatedError."""
        ...


@dataclass
class CognitoTokenVerifier:
    """Verifies RS256 access tokens issued by a Cognito user pool."""

    region: str
    user_pool_id: str
    client_id: str | None = None
    _jwk_client: Any = None

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    def _client(self) -> PyJWKClient:
        if self._jwk_client is None:
            # PyJWKClient caches keys; a new kid triggers one refetch.
            self._jwk_client = PyJWKClient(f"{self.issuer}/.well-known/jwks.json")
        return self._jwk_client

    def verify(self, token: str) -> dict:
        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise UnauthenticatedError("token has expired") from None
        except jwt.InvalidTokenError as exc:
            raise UnauthenticatedError(f"invalid token: {exc}") from None

        token_use = claims.get("token_use")
        if token_use not in ("access", "id"):
            raise UnauthenticatedError("unexpected token_use claim")

        if self.client_id:
            # Cognito records the app client in a *different* claim depending
            # on the token type: `client_id` on an access token, `aud` on an
            # ID token. `verify_aud` is off above because an access token has
            # no `aud` at all, so PyJWT cannot do this check for us.
            #
            # This previously read:
            #
            #     if claims.get("client_id") not in (None, self.client_id):
            #
            # which accepted a token whose `client_id` claim was simply
            # absent -- and an ID token never has one. Combined with
            # `verify_aud: False`, an ID token minted for a *different* app
            # client in the same user pool would have passed every check:
            # same signing keys, same issuer, `token_use` allowed, audience
            # never examined. Not exploitable as deployed, because the stack
            # creates exactly one app client, but adding a second one -- a
            # mobile client, a test client -- would have opened it silently,
            # which is the worst way for a boundary to move.
            #
            # Now each token type is audienced against the claim it actually
            # carries, and a missing claim fails rather than skipping.
            presented = claims.get("client_id") if token_use == "access" else claims.get("aud")
            # Per RFC 7519 `aud` may be a list. Cognito emits a string, but
            # accepting both costs nothing and avoids a confusing rejection.
            allowed = presented if isinstance(presented, (list, tuple)) else [presented]
            if self.client_id not in allowed:
                raise UnauthenticatedError("token was not issued for this client")
        return claims


@dataclass
class LocalTokenVerifier:
    """Local-development verifier (ADR-0011).

    Issues and verifies RS256 tokens with the same claim shape as Cognito using a
    dev keypair. The *verification path* is identical in structure to production;
    only the key source differs. This is a documented divergence, never presented
    as having tested Cognito itself.
    """

    public_key_pem: bytes
    issuer: str = "lifelink-local"

    def __post_init__(self) -> None:
        # A missing key file used to produce an empty byte string here, which
        # made every token fail to verify with a confusing error rather than
        # saying the key was absent. Refuse at construction instead: an
        # authenticator that cannot verify anything must not be built.
        if not self.public_key_pem or not self.public_key_pem.strip():
            raise EnvironmentConfigurationError(
                "the local development verifier was constructed without a public "
                "key. Run 'python scripts/dev.py keys' to generate the local "
                "keypair, or set LOCAL_JWT_PUBLIC_KEY to its path."
            )

    def verify(self, token: str) -> dict:
        try:
            claims = jwt.decode(
                token,
                self.public_key_pem,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise UnauthenticatedError("token has expired") from None
        except jwt.InvalidTokenError as exc:
            raise UnauthenticatedError(f"invalid token: {exc}") from None
        return claims


def issue_local_token(
    private_key_pem: bytes,
    *,
    subject: str,
    email: str | None = None,
    ttl_seconds: int = 3600,
    issuer: str = "lifelink-local",
    extra_claims: dict | None = None,
) -> str:
    """Mint a development token. Refuses outside a permitted local environment.

    The refusal is here as well as in the service container because this
    function is what actually produces a credential. A guard on the verifier
    alone would still leave a minting primitive reachable from any code path
    that imported this module.
    """
    if in_aws_execution_environment():
        raise EnvironmentConfigurationError(
            "refusing to mint a local development token inside an AWS execution "
            "environment"
        )
    if not is_local_environment():
        raise EnvironmentConfigurationError(
            f"refusing to mint a local development token while "
            f"LIFELINK_ENV={environment_name()!r} is not a local environment"
        )

    now = int(time.time())
    claims = {
        "sub": subject,
        "iss": issuer,
        "iat": now,
        "exp": now + ttl_seconds,
        "token_use": "access",
    }
    if email:
        claims["email"] = email
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, private_key_pem, algorithm="RS256")


class UserDirectory(Protocol):
    def get_principal(self, user_id: str) -> Principal | None:
        ...


@dataclass
class Authenticator:
    """Turns a raw Authorization header into a Principal."""

    verifier: TokenVerifier
    directory: UserDirectory
    #: Creates a minimal profile for a verified subject we have not seen.
    #: Optional so tests and the local path can omit it; when absent, an
    #: unknown subject is refused exactly as before.
    provisioner: Callable[..., object] | None = None

    def authenticate(self, authorization_header: str | None) -> Principal:
        if not authorization_header:
            return ANONYMOUS
        parts = authorization_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise UnauthenticatedError("Authorization header must be 'Bearer <token>'")

        claims = self.verifier.verify(parts[1])
        subject = claims.get("sub")
        if not subject:
            raise UnauthenticatedError("token has no subject claim")

        # Authoritative state comes from our own store, not from the token.
        principal = self.directory.get_principal(subject)

        if principal is None:  # noqa: SIM102 - the inner condition has its own rationale below
            # A valid token from a user pool account we have never seen. This
            # used to be a dead end -- "authenticated subject has no LifeLink
            # account" -- which anyone who signed up through Cognito hit on
            # their very first request, with nothing in the product able to
            # fix it.
            #
            # Provision a minimal profile instead: DONOR role, no
            # organization. The role assignment is the security property here.
            # A hospital or blood bank role would reach other organizations'
            # data, so those are never self-assigned; they are granted by an
            # administrator after verification. No organization means every
            # organization-scoped check refuses by construction.
            #
            # Only ever reached for a token this service has already verified
            # against the pool's keys, so the subject is genuine.
            if self.provisioner is not None:
                self.provisioner(
                    user_id=subject,
                    email=claims.get("email"),
                    display_name=claims.get("name") or claims.get("username"),
                )
                principal = self.directory.get_principal(subject)

        if principal is None:
            raise UnauthenticatedError("authenticated subject has no LifeLink account")
        return principal


# --- The authorization decorator ---------------------------------------------

# Resolves the organization that owns the resource a request targets.
# Returning None means "not organization-scoped for this call".
ResourceOwnerResolver = Callable[[dict, RequestContext], str | None]


def requires(
    permission: Permission | None = None,
    *,
    resource_owner: ResourceOwnerResolver | None = None,
    allow_anonymous: bool = False,
):
    """Wrap a handler with authentication, permission and organization checks.

    ``resource_owner`` is how IDOR is prevented: the handler declares how to find
    the owning organization of the thing being touched, and the comparison happens
    here rather than inside the handler where it can be forgotten.
    """

    def decorator(handler: Callable[[dict, RequestContext], dict]):
        @functools.wraps(handler)
        def wrapper(event: dict, context: RequestContext) -> dict:
            principal = context.principal

            # A protected route must still refuse a bad token. If
            # build_context captured a failure, surface it here with its
            # original reason -- "token has expired" is far more useful to a
            # client than a generic "authentication required".
            if not allow_anonymous and context.auth_error is not None:
                raise context.auth_error

            if not allow_anonymous and principal is ANONYMOUS:
                raise UnauthenticatedError("authentication required")

            # A valid token from a suspended account must not act (spec 8.1).
            if principal is not ANONYMOUS and not principal.is_active:
                raise AccountSuspendedError(
                    "this account is not active",
                    details={"accountStatus": principal.account_status},
                )

            if permission is not None and not principal.has(permission):
                raise ForbiddenError(
                    "you do not have permission to perform this action",
                    details={"required": permission.value},
                )

            if permission is not None and is_organization_scoped(permission) and resource_owner:
                owner_org = resource_owner(event, context)
                if owner_org is not None:
                    if principal.organization_id is None:
                        raise CrossOrganizationError(
                            "this action requires organization membership"
                        )
                    if owner_org != principal.organization_id:
                        # Deliberately does not reveal which organization owns it.
                        raise CrossOrganizationError(
                            "this resource belongs to another organization"
                        )

            return handler(event, context)

        wrapper.__lifelink_permission__ = permission  # type: ignore[attr-defined]
        wrapper.__lifelink_protected__ = True  # type: ignore[attr-defined]
        wrapper.__lifelink_allows_anonymous__ = allow_anonymous  # type: ignore[attr-defined]
        return wrapper

    return decorator


def build_context(
    event: dict,
    authenticator: Authenticator | None = None,
) -> RequestContext:
    """Construct the per-request context from an API Gateway-style event."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    correlation_id = headers.get("x-correlation-id") or new_correlation_id()

    principal = ANONYMOUS
    auth_error: Exception | None = None
    if authenticator is not None:
        try:
            principal = authenticator.authenticate(headers.get("authorization"))
        except LifeLinkError as exc:
            # Deliberately captured, not raised.
            #
            # This used to raise here, which meant a single unusable token --
            # expired, malformed, or belonging to a subject with no LifeLink
            # profile -- returned 401 from *every* route, including the public
            # ones. A signed-in user whose session had gone stale could not
            # browse blood availability, see facilities, or load the reference
            # data the home page needs. The failure had nothing to do with the
            # page they were on.
            #
            # The authorization decision belongs to requires(), which knows
            # whether the route tolerates an anonymous caller. It re-raises this
            # for every protected route, so nothing is weakened: a bad token
            # still cannot reach a protected handler.
            auth_error = exc
            principal = ANONYMOUS

    request_context = event.get("requestContext") or {}
    identity = request_context.get("identity") or {}
    http = request_context.get("http") or {}

    return RequestContext(
        correlation_id=correlation_id,
        principal=principal,
        source_ip=identity.get("sourceIp") or http.get("sourceIp"),
        user_agent=headers.get("user-agent"),
        idempotency_key=headers.get("idempotency-key"),
        auth_error=auth_error,
    )


def is_local_mode() -> bool:
    """Whether local development behaviour is permitted here.

    Delegates to :func:`appcore.environment.is_local_environment`, which raises
    rather than returning True inside an AWS execution environment. This used to
    be a bare ``os.environ.get("LIFELINK_ENV", "local")`` comparison, whose
    default meant an unset variable in Lambda selected the development token
    verifier instead of Cognito.
    """
    return is_local_environment()


__all__ = [
    "Authenticator",
    "CognitoTokenVerifier",
    "LocalTokenVerifier",
    "LifeLinkError",
    "build_context",
    "is_local_mode",
    "issue_local_token",
    "requires",
]
