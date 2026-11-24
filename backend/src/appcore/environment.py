"""Environment resolution, and the refusal that keeps local auth local.

The local development authenticator (ADR-0011) verifies RS256 tokens against a
keypair generated on a developer's machine. That is safe on a laptop and
catastrophic in a deployment: anyone holding the matching private key could
mint a token for any subject.

Before this module existed, the only thing standing between those two
situations was the *absence of a file*. Worse, ``LIFELINK_ENV`` defaulted to
``"local"``, so an unset variable in Lambda selected the local verifier rather
than Cognito. Nothing announced it. The symptom would have been "authentication
mysteriously rejects everything" if the key file were missing, or a total
authentication bypass if the key file were ever bundled into the deployment
package.

This module replaces that accident with three explicit refusals:

1.  In an AWS execution environment, ``LIFELINK_ENV`` must be set. There is no
    default, because the old default was the dangerous one.
2.  In an AWS execution environment, a local environment name is refused
    outright, even if someone sets it deliberately.
3.  The local verifier refuses to be constructed without a real key, so a
    missing key file is a startup failure rather than a silent
    everything-is-rejected state.

Each refusal raises at construction time, before a single request is served.
Failing to start is the correct outcome: a deployment that cannot verify
identities must not accept traffic.
"""

from __future__ import annotations

import os

LOCAL_ENVIRONMENT_NAMES = frozenset({"local", "test"})
DEPLOYED_ENVIRONMENT_NAMES = frozenset({"dev", "development", "staging", "prod", "production"})

#: Variables AWS sets in its own managed compute environments. We do not trust
#: any single one of these to be present forever, so any of them counts.
_AWS_EXECUTION_MARKERS = (
    "AWS_LAMBDA_FUNCTION_NAME",
    "AWS_EXECUTION_ENV",
    "LAMBDA_TASK_ROOT",
)


class EnvironmentConfigurationError(RuntimeError):
    """The process is configured in a way that cannot be made safe.

    Deliberately not a ``LifeLinkError``: this is not a request that failed, it
    is a process that must not start. It carries no HTTP status because there is
    no request to answer.
    """


def in_aws_execution_environment() -> bool:
    """True when running inside AWS-managed compute (Lambda).

    Checks several markers rather than one, so that a change to any single
    AWS-provided variable cannot silently re-open the hole this module closes.
    """
    return any(os.environ.get(marker) for marker in _AWS_EXECUTION_MARKERS)


def environment_name() -> str:
    """The configured environment name, lowercased.

    Raises when running in AWS with nothing configured. Outside AWS the default
    is ``"local"``, which is the safe direction to be wrong in: a developer's
    machine gets local behaviour, and a deployment gets a refusal.
    """
    raw = os.environ.get("LIFELINK_ENV")
    if raw is None or not raw.strip():
        if in_aws_execution_environment():
            raise EnvironmentConfigurationError(
                "LIFELINK_ENV is not set in an AWS execution environment. "
                "Refusing to start: an unset value used to mean 'local', which "
                "would select the development token verifier instead of Cognito. "
                "Set LIFELINK_ENV to one of: "
                f"{', '.join(sorted(DEPLOYED_ENVIRONMENT_NAMES))}."
            )
        return "local"
    return raw.strip().lower()


def is_local_environment() -> bool:
    """True only when local behaviour is both requested and permitted.

    In an AWS execution environment this always returns False — it raises first
    if local mode was requested, so there is no path on which a deployed
    process quietly takes the local branch.
    """
    name = environment_name()
    if name not in LOCAL_ENVIRONMENT_NAMES:
        return False

    if in_aws_execution_environment():
        raise EnvironmentConfigurationError(
            f"LIFELINK_ENV={name!r} requests local development mode, but this "
            "process is running in an AWS execution environment. Refusing to "
            "start: local mode verifies tokens against a development keypair "
            "rather than Cognito, which would allow anyone holding that private "
            "key to authenticate as any user. Set LIFELINK_ENV to a deployed "
            "environment name."
        )
    return True


def require_local_auth_allowed() -> None:
    """Assert that the local authenticator may be constructed here.

    Called by the service container immediately before building the local
    verifier. Separate from :func:`is_local_environment` so that the refusal is
    explicit at the one place that matters, and so a future caller cannot reach
    the local verifier through a different route without tripping this.
    """
    if in_aws_execution_environment():
        raise EnvironmentConfigurationError(
            "refusing to construct the local development authenticator inside an "
            "AWS execution environment"
        )
    if not is_local_environment():
        raise EnvironmentConfigurationError(
            f"refusing to construct the local development authenticator while "
            f"LIFELINK_ENV={environment_name()!r} is not a local environment"
        )


__all__ = [
    "DEPLOYED_ENVIRONMENT_NAMES",
    "EnvironmentConfigurationError",
    "LOCAL_ENVIRONMENT_NAMES",
    "environment_name",
    "in_aws_execution_environment",
    "is_local_environment",
    "require_local_auth_allowed",
]
