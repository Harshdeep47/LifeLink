#!/usr/bin/env python
"""Create Cognito users for the demo accounts and mint real Cognito tokens.

Why this is needed, stated plainly: the seeded accounts live in DynamoDB with
readable identifiers (``user-donor-1``), but Cognito issues a UUID ``sub``, and
the authorizer resolves a principal by the token's subject. So a Cognito user
signing in has no LifeLink account unless something maps the two. This script
is that something.

For each demo account it:

1.  Creates a Cognito user, with the welcome email suppressed and the address
    pre-verified, so nothing is sent to anyone. Addresses use the reserved
    ``.invalid`` TLD (RFC 2606), which can never resolve to a real mailbox.
2.  Reads the user's Cognito ``sub``.
3.  Writes a LifeLink principal record keyed by that ``sub``, mirroring the
    seeded account's roles, organization and account status. The readable
    record is left in place, so both identifiers resolve to the same person
    and local development is unaffected.
4.  Optionally mints a real access token via ``AdminInitiateAuth``.

**The token is a genuine Cognito token**, verified in the deployed API by the
real ``CognitoTokenVerifier`` against the pool's JWKS. The demonstration
therefore exercises the production authentication path. What it does *not*
exercise is the browser redirect to Cognito managed login: that
authorization-code-with-PKCE exchange is **not implemented in the frontend**,
so a presenter pastes a token into the sign-in page instead. That limitation is
recorded in KNOWN_LIMITATIONS.md rather than papered over.

Usage::

    python scripts/provision_demo_logins.py --stack lifelink-dev
    python scripts/provision_demo_logins.py --stack lifelink-dev --token user-donor-1
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

# Never inherit the local-development placeholders; see seed_cloud.py.
os.environ.pop("DYNAMODB_ENDPOINT", None)
for _ph in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    if os.environ.get(_ph) == "local":
        os.environ.pop(_ph)

#: The demo accounts worth being able to sign in as, and what each shows.
DEMO_ACCOUNTS = [
    ("user-donor-1", "Donor with verified donations and a milestone"),
    ("user-bb-admin-1", "Blood bank admin: inventory, corrections, verification"),
    ("user-bb-staff-1", "Blood bank staff: can update stock, cannot verify"),
    ("user-hosp-auth-1", "Hospital authorizer: can certify priority"),
    ("user-hosp-staff-1", "Hospital staff: can request, cannot certify"),
    ("user-camp-org-1", "Camp organizer"),
    ("user-admin-1", "Platform administrator: verification, suspension, audit"),
    ("user-suspended-1", "Suspended account: valid token, every action refused"),
]

PASSWORD_FILE = ROOT / ".local-keys" / "demo-logins.txt"


def generate_password() -> str:
    """A password that satisfies the pool policy, freshly generated each run.

    Not hard-coded: a fixed password committed to a repository is a credential
    leak even on a demo environment, and this one guards an internet-reachable
    sign-in.
    """
    alphabet = string.ascii_letters + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(16))
    return f"Demo-{body}!7"


def stack_outputs(stack_name: str, region: str) -> dict[str, str]:
    import boto3

    cfn = boto3.client("cloudformation", region_name=region)
    stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    params = {p["ParameterKey"]: p["ParameterValue"] for p in stacks[0].get("Parameters", [])}
    env = (params.get("Environment") or "").lower()
    if env not in ("dev", "development"):
        print(f"REFUSING: stack Environment is {env!r}; this script is for dev only.",
              file=sys.stderr)
        raise SystemExit(2)
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


def ensure_cognito_user(idp, pool_id: str, user_id: str, password: str) -> str:
    """Create (or find) the Cognito user and return its sub."""
    from botocore.exceptions import ClientError

    email = f"{user_id}@demo.lifelink.invalid"
    try:
        idp.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            # No email is sent. The account is synthetic and the address is
            # unroutable by design.
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": user_id},
            ],
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "UsernameExistsException":
            raise

    idp.admin_set_user_password(
        UserPoolId=pool_id, Username=email, Password=password, Permanent=True
    )
    described = idp.admin_get_user(UserPoolId=pool_id, Username=email)
    for attr in described["UserAttributes"]:
        if attr["Name"] == "sub":
            return attr["Value"]
    raise SystemExit(f"Cognito returned no sub for {email}")


def link_principal(user_id: str, sub: str, now) -> dict:
    """Copy the seeded account onto the Cognito subject.

    Writes a second principal record rather than renaming the first, so the
    readable identifier keeps working for local development and for anything
    that already references it.
    """
    from repositories.identity_repo import IdentityRepository

    identity = IdentityRepository()
    source = identity.get_user(user_id)
    if source is None:
        raise SystemExit(
            f"{user_id} is not in the deployed database. Run seed_cloud.py first."
        )

    # Idempotent: this script must be re-runnable, because a presenter will
    # need a fresh token tomorrow and tokens expire in an hour. On the second
    # run the Cognito user and the linked principal already exist, which is
    # success, not an error.
    if identity.get_user(sub) is not None:
        return {"userId": sub, "alreadyLinked": True}

    created = identity.create_user(
        user_id=sub,
        email=source.get("email") or f"{user_id}@demo.lifelink.invalid",
        display_name=source.get("displayName") or user_id,
        roles=list(source.get("roles", [])),
        organization_id=source.get("organizationId"),
        now=now,
        account_status=source.get("accountStatus", "ACTIVE"),
        extra={
            "demoData": True,
            "dataSource": "SYNTHETIC",
            "environment": "DEVELOPMENT",
            # Recorded so an operator reading the table can see why two records
            # describe one person.
            "cognitoLinkedFrom": user_id,
            "identifierKind": "COGNITO_SUB",
        },
    )
    return created


def mint_token(idp, pool_id: str, client_id: str, user_id: str, password: str) -> str:
    email = f"{user_id}@demo.lifelink.invalid"
    res = idp.admin_initiate_auth(
        UserPoolId=pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": password},
    )
    result = res.get("AuthenticationResult") or {}
    token = result.get("AccessToken")
    if not token:
        raise SystemExit(
            "Cognito did not return an access token; challenge: "
            f"{res.get('ChallengeName')}"
        )
    return token


def main() -> int:
    from datetime import datetime, timezone

    import boto3

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="lifelink-dev")
    parser.add_argument("--region", default="ap-southeast-2")
    parser.add_argument("--token", default=None,
                        help="also print a fresh access token for this account")
    parser.add_argument("--password", default=None,
                        help="reuse an existing password instead of generating one")
    args = parser.parse_args()

    outputs = stack_outputs(args.stack, args.region)
    pool_id = outputs["UserPoolId"]
    client_id = outputs["UserPoolClientId"]
    api = outputs.get("ApiEndpoint", "")
    print(f"User pool : {pool_id}")
    print(f"App client: {client_id}")

    os.environ["LIFELINK_ENV"] = "dev"
    os.environ["LIFELINK_TABLE_PREFIX"] = "lifelink-dev"
    os.environ["AWS_REGION"] = args.region

    idp = boto3.client("cognito-idp", region_name=args.region)
    now = datetime.now(timezone.utc)
    password = args.password or generate_password()

    print("\nProvisioning demo logins (no email is sent; addresses are .invalid)")
    print("-" * 74)
    rows = []
    for user_id, description in DEMO_ACCOUNTS:
        sub = ensure_cognito_user(idp, pool_id, user_id, password)
        link_principal(user_id, sub, now)
        rows.append((user_id, sub, description))
        print(f"  {user_id:<20} -> {sub}")

    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    PASSWORD_FILE.write_text(
        "LifeLink deployed demo logins. Synthetic accounts only.\n"
        "This file is gitignored (.local-keys/) and must not be committed.\n\n"
        f"user pool : {pool_id}\n"
        f"app client: {client_id}\n"
        f"api       : {api}\n"
        f"password  : {password}\n\n"
        + "".join(f"{u}@demo.lifelink.invalid    {d}\n" for u, _, d in rows),
        encoding="utf-8",
    )
    print("-" * 74)
    print(f"  password for every demo account: {password}")
    print(f"  saved to {PASSWORD_FILE} (gitignored)")

    if args.token:
        token = mint_token(idp, pool_id, client_id, args.token, password)
        print(f"\nReal Cognito access token for {args.token}:\n")
        print(token)
        print("\nPaste this on the deployed sign-in page. It is verified by the")
        print("API against the Cognito pool's JWKS, and expires in 1 hour.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
