"""The local authenticator must not be reachable from a deployment.

These tests exist because of a real hole. ``LIFELINK_ENV`` defaulted to
``"local"``, so a Lambda that was deployed without that variable set would
select the local development token verifier instead of Cognito. The only thing
preventing an authentication bypass was that the development keypair happened
not to be in the deployment package.

Every test here asserts a *refusal*. There is deliberately no test asserting
that local mode works inside an AWS execution environment, because it must not.
"""

from __future__ import annotations

import pytest

from appcore.auth import LocalTokenVerifier, issue_local_token
from appcore.environment import (
    EnvironmentConfigurationError,
    environment_name,
    in_aws_execution_environment,
    is_local_environment,
    require_local_auth_allowed,
)

AWS_MARKERS = ("AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "LAMBDA_TASK_ROOT")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start every test from a known-empty environment.

    The real process environment leaks otherwise: the test runner itself may set
    LIFELINK_ENV, and a developer running under an AWS toolchain could have a
    marker set.
    """
    monkeypatch.delenv("LIFELINK_ENV", raising=False)
    for marker in AWS_MARKERS:
        monkeypatch.delenv(marker, raising=False)


# --- Detection of the AWS execution environment ------------------------------


def test_no_markers_is_not_an_aws_environment():
    assert in_aws_execution_environment() is False


@pytest.mark.parametrize("marker", AWS_MARKERS)
def test_any_single_marker_is_enough(monkeypatch, marker):
    """Any one marker counts, so a change to one cannot re-open the hole."""
    monkeypatch.setenv(marker, "lifelink-prod-api")
    assert in_aws_execution_environment() is True


@pytest.mark.parametrize("marker", AWS_MARKERS)
def test_empty_marker_does_not_count(monkeypatch, marker):
    monkeypatch.setenv(marker, "")
    assert in_aws_execution_environment() is False


# --- Environment name resolution ---------------------------------------------


def test_defaults_to_local_outside_aws():
    """Safe direction to be wrong in: a laptop gets local, a deployment refuses."""
    assert environment_name() == "local"


def test_unset_environment_in_aws_refuses(monkeypatch):
    """The regression test for the actual defect."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "lifelink-prod-api")
    with pytest.raises(EnvironmentConfigurationError) as excinfo:
        environment_name()
    assert "LIFELINK_ENV is not set" in str(excinfo.value)


def test_blank_environment_in_aws_refuses(monkeypatch):
    """An empty string is not a configured value."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "lifelink-prod-api")
    monkeypatch.setenv("LIFELINK_ENV", "   ")
    with pytest.raises(EnvironmentConfigurationError):
        environment_name()


@pytest.mark.parametrize("raw,expected", [("PROD", "prod"), (" Production ", "production")])
def test_name_is_normalised(monkeypatch, raw, expected):
    monkeypatch.setenv("LIFELINK_ENV", raw)
    assert environment_name() == expected


# --- is_local_environment ----------------------------------------------------


@pytest.mark.parametrize("name", ["local", "test", "LOCAL", "Test"])
def test_local_names_are_local_outside_aws(monkeypatch, name):
    monkeypatch.setenv("LIFELINK_ENV", name)
    assert is_local_environment() is True


@pytest.mark.parametrize("name", ["dev", "development", "staging", "prod", "production"])
def test_deployed_names_are_not_local(monkeypatch, name):
    monkeypatch.setenv("LIFELINK_ENV", name)
    assert is_local_environment() is False


@pytest.mark.parametrize("name", ["local", "test"])
@pytest.mark.parametrize("marker", AWS_MARKERS)
def test_local_mode_in_aws_refuses(monkeypatch, name, marker):
    """Even deliberately requesting local mode in Lambda is refused."""
    monkeypatch.setenv(marker, "lifelink-prod-api")
    monkeypatch.setenv("LIFELINK_ENV", name)
    with pytest.raises(EnvironmentConfigurationError) as excinfo:
        is_local_environment()
    message = str(excinfo.value)
    assert "AWS execution environment" in message
    assert "Cognito" in message


def test_deployed_name_in_aws_is_fine(monkeypatch):
    """The guard refuses local mode, not deployment itself."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "lifelink-prod-api")
    monkeypatch.setenv("LIFELINK_ENV", "prod")
    assert is_local_environment() is False


def test_unknown_name_is_not_local(monkeypatch):
    """An unrecognised name must not fall through to local behaviour."""
    monkeypatch.setenv("LIFELINK_ENV", "banana")
    assert is_local_environment() is False


# --- require_local_auth_allowed ----------------------------------------------


def test_require_allows_local_outside_aws(monkeypatch):
    monkeypatch.setenv("LIFELINK_ENV", "local")
    require_local_auth_allowed()  # must not raise


@pytest.mark.parametrize("marker", AWS_MARKERS)
def test_require_refuses_in_aws(monkeypatch, marker):
    monkeypatch.setenv(marker, "lifelink-prod-api")
    monkeypatch.setenv("LIFELINK_ENV", "prod")
    with pytest.raises(EnvironmentConfigurationError):
        require_local_auth_allowed()


def test_require_refuses_for_deployed_name(monkeypatch):
    monkeypatch.setenv("LIFELINK_ENV", "production")
    with pytest.raises(EnvironmentConfigurationError):
        require_local_auth_allowed()


# --- The verifier refuses to exist without a key -----------------------------


@pytest.mark.parametrize("key", [b"", b"   ", b"\n"])
def test_local_verifier_refuses_empty_key(key):
    """A missing key file used to become an empty byte string here.

    The old behaviour built a verifier that rejected every token with a
    confusing signature error. Refusing at construction names the real problem.
    """
    with pytest.raises(EnvironmentConfigurationError) as excinfo:
        LocalTokenVerifier(public_key_pem=key)
    assert "dev.py keys" in str(excinfo.value)


def test_local_verifier_accepts_a_key():
    verifier = LocalTokenVerifier(public_key_pem=b"-----BEGIN PUBLIC KEY-----\nx\n")
    assert verifier.issuer == "lifelink-local"


# --- Token minting is guarded at the source ----------------------------------


@pytest.mark.parametrize("marker", AWS_MARKERS)
def test_minting_refuses_in_aws(monkeypatch, marker):
    """Guarding the verifier is not enough; minting is the credential-producing step."""
    monkeypatch.setenv(marker, "lifelink-prod-api")
    monkeypatch.setenv("LIFELINK_ENV", "prod")
    with pytest.raises(EnvironmentConfigurationError):
        issue_local_token(b"irrelevant", subject="user-attacker-1")


def test_minting_refuses_for_deployed_name(monkeypatch):
    monkeypatch.setenv("LIFELINK_ENV", "production")
    with pytest.raises(EnvironmentConfigurationError):
        issue_local_token(b"irrelevant", subject="user-attacker-1")


def test_minting_refuses_before_touching_the_key(monkeypatch):
    """The refusal must precede any use of the private key material.

    Passing a deliberately invalid key proves the guard runs first: if the guard
    were after the signing call, this would raise a cryptography error instead.
    """
    monkeypatch.setenv("LIFELINK_ENV", "production")
    with pytest.raises(EnvironmentConfigurationError):
        issue_local_token(b"not-a-key-at-all", subject="user-1")


# --- The container's branch --------------------------------------------------


def test_container_refuses_local_authenticator_in_aws(monkeypatch):
    """End to end: the wiring itself refuses, not just the helpers."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "lifelink-prod-api")
    monkeypatch.setenv("LIFELINK_ENV", "local")

    from services import container

    with pytest.raises(EnvironmentConfigurationError):
        container.is_local()


def test_container_requires_cognito_pool_outside_local(monkeypatch):
    """No fallback verifier exists outside local mode, by design."""
    monkeypatch.setenv("LIFELINK_ENV", "prod")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)

    from services import container

    with pytest.raises(EnvironmentConfigurationError) as excinfo:
        container._build_authenticator(repos=None)  # type: ignore[arg-type]
    assert "COGNITO_USER_POOL_ID" in str(excinfo.value)
