"""The production Cognito token verifier.

This class had no tests. The local development verifier was exercised, the
authorization matrix was exercised, but the component that decides whether a
*real* request is authenticated at all was not — so the one boundary that
cannot fail safely was the one nothing checked.

Tests sign real RS256 tokens with a throwaway key and inject the signing key,
so the JWKS fetch is the only thing stubbed. Everything else — signature,
issuer, expiry, required claims, `token_use`, audience — runs the real code.

The audience cases are the point. Cognito records the app client in a
different claim depending on token type (`client_id` on an access token, `aud`
on an ID token), and `verify_aud` is necessarily off because an access token
has no `aud`. Checking only one claim leaves the other unaudienced.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from appcore.auth import CognitoTokenVerifier
from domain.errors import UnauthenticatedError

REGION = "ap-southeast-2"
POOL = "ap-southeast-2_TESTPOOL"
CLIENT = "3xampleclientid"
OTHER_CLIENT = "0therclientid"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_pem, key.public_key()


class _StubJwkClient:
    """Stands in for the JWKS endpoint. Returns one fixed public key."""

    def __init__(self, public_key):
        self._public_key = public_key
        self.calls = 0

    def get_signing_key_from_jwt(self, token):  # noqa: ARG002 - signature is the contract
        self.calls += 1
        return type("Key", (), {"key": self._public_key})()


def make_verifier(keypair, *, client_id: str | None = CLIENT) -> CognitoTokenVerifier:
    _, public_key = keypair
    verifier = CognitoTokenVerifier(
        region=REGION, user_pool_id=POOL, client_id=client_id
    )
    verifier._jwk_client = _StubJwkClient(public_key)
    return verifier


def sign(keypair, claims: dict, *, issuer: str = ISSUER, expires_in_s: int = 300) -> str:
    private_pem, _ = keypair
    now = datetime.now(UTC)
    payload = {
        "sub": "cognito-subject-1",
        "iss": issuer,
        "exp": now + timedelta(seconds=expires_in_s),
        "iat": now,
        **claims,
    }
    return jwt.encode(payload, private_pem, algorithm="RS256")


def access_token(keypair, **overrides) -> str:
    claims = {"token_use": "access", "client_id": CLIENT}
    claims.update(overrides)
    return sign(keypair, claims)


def id_token(keypair, **overrides) -> str:
    claims = {"token_use": "id", "aud": CLIENT}
    claims.update(overrides)
    return sign(keypair, claims)


class TestIssuerAndSignature:
    def test_a_valid_access_token_is_accepted(self, keypair):
        claims = make_verifier(keypair).verify(access_token(keypair))
        assert claims["sub"] == "cognito-subject-1"

    def test_the_issuer_is_derived_from_region_and_pool(self, keypair):
        assert make_verifier(keypair).issuer == ISSUER

    def test_a_token_from_another_user_pool_is_refused(self, keypair):
        other = f"https://cognito-idp.{REGION}.amazonaws.com/ap-southeast-2_OTHERPOOL"
        token = sign(keypair, {"token_use": "access", "client_id": CLIENT}, issuer=other)
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify(token)

    def test_a_token_signed_by_a_different_key_is_refused(self, keypair):
        stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        stranger_pem = stranger.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "x",
                "iss": ISSUER,
                "exp": now + timedelta(seconds=300),
                "token_use": "access",
                "client_id": CLIENT,
            },
            stranger_pem,
            algorithm="RS256",
        )
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify(token)

    def test_an_unsigned_token_is_refused(self, keypair):
        token = jwt.encode(
            {"sub": "x", "iss": ISSUER, "token_use": "access", "client_id": CLIENT},
            key="",
            algorithm="none",
        )
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify(token)

    def test_garbage_is_refused_without_leaking_an_exception_type(self, keypair):
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify("not-a-token")


class TestExpiryAndRequiredClaims:
    def test_an_expired_token_is_refused_with_a_clear_message(self, keypair):
        token = access_token(keypair, exp=datetime.now(UTC) - timedelta(minutes=1))
        with pytest.raises(UnauthenticatedError) as caught:
            make_verifier(keypair).verify(token)
        assert "expired" in str(caught.value)

    @pytest.mark.parametrize("missing", ["exp", "sub"])
    def test_a_token_missing_a_required_claim_is_refused(self, keypair, missing):
        private_pem, _ = keypair
        now = datetime.now(UTC)
        payload = {
            "sub": "cognito-subject-1",
            "iss": ISSUER,
            "exp": now + timedelta(seconds=300),
            "token_use": "access",
            "client_id": CLIENT,
        }
        del payload[missing]
        token = jwt.encode(payload, private_pem, algorithm="RS256")
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify(token)


class TestTokenUse:
    def test_an_id_token_for_this_client_is_accepted(self, keypair):
        claims = make_verifier(keypair).verify(id_token(keypair))
        assert claims["token_use"] == "id"

    @pytest.mark.parametrize("bad", ["refresh", "", "ACCESS", None])
    def test_any_other_token_use_is_refused(self, keypair, bad):
        token = sign(keypair, {"token_use": bad, "client_id": CLIENT})
        with pytest.raises(UnauthenticatedError) as caught:
            make_verifier(keypair).verify(token)
        assert "token_use" in str(caught.value)

    def test_a_token_with_no_token_use_claim_is_refused(self, keypair):
        token = sign(keypair, {"client_id": CLIENT})
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify(token)


class TestAudience:
    """Each token type must be audienced against the claim it carries."""

    def test_an_access_token_for_another_client_is_refused(self, keypair):
        token = access_token(keypair, client_id=OTHER_CLIENT)
        with pytest.raises(UnauthenticatedError) as caught:
            make_verifier(keypair).verify(token)
        assert "not issued for this client" in str(caught.value)

    def test_an_id_token_for_another_client_is_refused(self, keypair):
        """The case the previous implementation let through.

        Same user pool, so the signature and issuer are genuine. An ID token
        has no `client_id` claim, and the old check skipped verification when
        that claim was absent, while `verify_aud` is off. Every gate passed
        and the audience was never examined.
        """
        token = id_token(keypair, aud=OTHER_CLIENT)
        with pytest.raises(UnauthenticatedError) as caught:
            make_verifier(keypair).verify(token)
        assert "not issued for this client" in str(caught.value)

    def test_an_access_token_with_no_client_id_claim_is_refused(self, keypair):
        """A missing claim must fail, not skip the check."""
        token = sign(keypair, {"token_use": "access"})
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify(token)

    def test_an_id_token_with_no_audience_claim_is_refused(self, keypair):
        token = sign(keypair, {"token_use": "id"})
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify(token)

    def test_an_audience_list_containing_this_client_is_accepted(self, keypair):
        # RFC 7519 allows a list. Cognito emits a string, but rejecting a
        # valid list would be a confusing failure.
        claims = make_verifier(keypair).verify(id_token(keypair, aud=[CLIENT, "other"]))
        assert claims["token_use"] == "id"

    def test_an_audience_list_without_this_client_is_refused(self, keypair):
        token = id_token(keypair, aud=[OTHER_CLIENT, "another"])
        with pytest.raises(UnauthenticatedError):
            make_verifier(keypair).verify(token)

    def test_with_no_client_id_configured_the_audience_check_is_skipped(self, keypair):
        """Unchanged behaviour for a deployment that did not set the client id.

        Not ideal, but it is the documented existing contract and narrowing it
        here would reject traffic on an environment that works today. The
        container supplies COGNITO_CLIENT_ID in every deployed environment.
        """
        verifier = make_verifier(keypair, client_id=None)
        assert verifier.verify(access_token(keypair, client_id=OTHER_CLIENT))
        assert verifier.verify(id_token(keypair, aud=OTHER_CLIENT))


class TestJwksClientReuse:
    def test_the_signing_key_client_is_created_once_and_reused(self, keypair):
        verifier = make_verifier(keypair)
        verifier.verify(access_token(keypair))
        verifier.verify(access_token(keypair))
        # Two verifications, one cached client, two key lookups through it.
        assert verifier._jwk_client.calls == 2
