"""Integration test for the JWT authorizer contract (Task 17.1).

Authentication is delegated entirely to Amazon Cognito. API Gateway's native
JWT authorizer validates the Cognito token at the edge (issuer, audience,
signature, expiry) and places the verified claims on the request context. The
Logstead app performs **no** token verification of its own — it only reads the
authorizer-populated claims via ``current_user`` and scopes data to the
resulting identity.

This test validates that auth *contract* at the boundary that exists today: the
seam between the authorizer-populated request context and the application. It
asserts, end to end against moto-backed DynamoDB, that a protected flow (a
user-scoped property read) is reachable **only** when verified claims are
present, and that the app accepts those claims as-is without re-verifying the
token.

Note: full route-level guarding (an unauthenticated HTTP request returning 401
before any service runs) is completed once the router/handler lands (Task
16.1); the router will depend on exactly the contract exercised here —
``current_user`` yields a ``UserContext`` when the authorizer populated claims
and raises ``AuthError`` (which the router maps to 401) when it did not.

Covers Requirements:
* 1.1 — sign-in delegated to the managed Identity_Provider (Cognito Hosted UI);
  the app never handles credentials, only the verified identity it is handed.
* 1.2 — an authenticated request (verified claims present) reaches the
  protected flow and resolves a session identity.
* 1.3 — a request the provider did not authenticate (no verified claims on the
  context) does not establish an identity and the protected action never runs.
* 1.4 — access to the Logstead API is authorized purely by the provider-issued
  token's verified claims; the app adds no token handling of its own.
"""

from __future__ import annotations

import ast
import inspect

import boto3
import pytest
from moto import mock_aws

from logstead.models.property import PropertyInput
from logstead.services import auth as auth_module
from logstead.services.auth import AuthError, current_user, user_id_of
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"


# --- Event builders: representative API Gateway HTTP API proxy events ---------


def _event_with_verified_claims(claims: dict) -> dict:
    """An HTTP API event whose JWT authorizer populated verified claims.

    This is the shape API Gateway hands the Lambda **after** the native Cognito
    JWT authorizer has validated the token at the edge.
    """
    return {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}


def _event_without_claims() -> dict:
    """An HTTP API event with no authorizer context at all.

    Represents a request the authorizer would have blocked (or a misconfigured /
    unauthenticated call): there is no verified identity for the app to read.
    """
    return {"requestContext": {}}


def _event_with_empty_authorizer() -> dict:
    """An HTTP API event whose authorizer block carries no verified claims."""
    return {"requestContext": {"authorizer": {"jwt": {"claims": {}}}}}


# --- moto-backed table for the downstream scoped-read flow --------------------


@pytest.fixture
def client():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb


@pytest.fixture
def repo(client):
    return DynamoRepository(client, TABLE_NAME)


def _protected_read(event: dict, repo: DynamoRepository):
    """The protected flow the router will guard: resolve identity, then read.

    Mirrors what the future handler does per request — read the authenticated
    user from the authorizer-populated context, then perform a user-scoped data
    operation. If ``current_user`` raises ``AuthError`` the protected action
    (the property read) never runs.
    """
    user = current_user(event)  # raises AuthError when no verified identity
    service = PropertyService(repo, user)
    return service.list()


# --- 1.2: verified claims present -> protected flow is reachable --------------


def test_protected_flow_reachable_with_verified_claims(repo):
    """With authorizer-populated claims, identity resolves and a scoped read runs."""
    claims = {
        "sub": "cognito-user-42",
        "cognito:username": "landlord",
        "email": "owner@example.com",
    }

    # Seed a property owned by this verified identity so the scoped read returns it.
    owner = PropertyService(repo, current_user(_event_with_verified_claims(claims)))
    created = owner.create(PropertyInput(name="Maple St", address_text="1 Maple St"))
    assert created.is_ok

    # The protected flow, driven only by the authorizer context, reaches the
    # data layer and returns the authenticated user's data.
    result = _protected_read(_event_with_verified_claims(claims), repo)

    assert [p.id for p in result] == [created.value.id]
    assert all(p.user_id == "cognito-user-42" for p in result)


def test_verified_identity_scopes_data_to_the_authenticated_user(repo):
    """Data is scoped to the token's ``sub``; one identity cannot see another's."""
    owner_claims = {"sub": "owner-sub", "cognito:username": "owner"}
    intruder_claims = {"sub": "intruder-sub", "cognito:username": "intruder"}

    owner = PropertyService(repo, current_user(_event_with_verified_claims(owner_claims)))
    owner.create(PropertyInput(name="P", address_text="A"))

    # A different verified identity reaches the flow but sees none of the
    # owner's data — authorization is by the provider-issued ``sub``.
    intruder_view = _protected_read(
        _event_with_verified_claims(intruder_claims), repo
    )
    assert intruder_view == []


# --- 1.3: no verified claims -> protected action never runs -------------------


@pytest.mark.parametrize(
    "event_builder",
    [
        _event_without_claims,
        _event_with_empty_authorizer,
    ],
    ids=["no-authorizer-context", "empty-claims"],
)
def test_protected_flow_blocked_without_verified_claims(event_builder, repo):
    """Without verified claims the flow raises AuthError before any data read.

    The router will map this ``AuthError`` to ``401 Unauthorized``. Here we
    prove the protected action is unreachable: no identity is fabricated and no
    scoped read occurs.
    """
    with pytest.raises(AuthError):
        _protected_read(event_builder(), repo)


def test_no_side_effects_when_identity_is_missing(repo):
    """A blocked (unauthenticated) request performs no data operation at all."""
    # Nothing was written by any authenticated user, so the table is empty and
    # stays empty: the protected read never executes.
    with pytest.raises(AuthError):
        _protected_read(_event_without_claims(), repo)

    # A subsequent legitimately-empty scoped read confirms no phantom data was
    # created by the blocked request.
    empty_but_authed = _protected_read(
        _event_with_verified_claims({"sub": "some-user"}), repo
    )
    assert empty_but_authed == []


# --- 1.1 / 1.4: the app performs NO token verification of its own -------------


def test_app_trusts_edge_and_does_not_reverify_token():
    """Arbitrary claims with a ``sub`` resolve — the app never re-verifies.

    There is no signature, issuer, audience, or expiry check in the app: it
    accepts whatever verified claims the edge authorizer handed it. An event
    carrying only an opaque ``sub`` (no real token, no ``exp``, no signature)
    resolves to a ``UserContext``, proving the app trusts the edge (Requirement
    1.4) and adds no token handling of its own.
    """
    # No ``exp``/``iat``/signature anywhere — just the verified subject.
    user = current_user(_event_with_verified_claims({"sub": "trusted-by-edge"}))

    assert user_id_of(user) == "trusted-by-edge"


def test_expired_looking_claims_are_still_accepted_by_the_app():
    """Even an obviously-stale ``exp`` is accepted: expiry is the edge's job.

    The authorizer rejects expired tokens before the app ever runs, so if the
    app receives claims it treats them as already-valid. This documents that the
    app does NOT perform expiry validation itself (Requirement 1.4).
    """
    user = current_user(
        _event_with_verified_claims(
            {"sub": "edge-validated", "exp": 0, "iat": 0}
        )
    )

    assert user.user_id == "edge-validated"
    # The stale exp/iat simply pass through as opaque claims — never inspected.
    assert user.claims.get("exp") == 0
    assert user.claims.get("iat") == 0


def test_auth_module_imports_no_jwt_or_crypto_library():
    """The app-side auth reads dict claims only — it imports no JWT/crypto lib.

    Guards against regressions where someone adds in-app token decoding or
    signature verification, which would violate the delegation contract
    (Requirements 1.1, 1.4): validation belongs to the edge authorizer. Note we
    inspect *imports*, not source text — the word "jwt" legitimately appears in
    ``auth.py`` because HTTP API nests claims under an ``authorizer["jwt"]``
    block; that is reading a dict key, not decoding a token.
    """
    tree = ast.parse(inspect.getsource(auth_module))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    # Any of these would indicate in-app token decoding / signature checking.
    crypto_or_jwt = {
        "jwt",  # PyJWT
        "jose",  # python-jose
        "jwcrypto",
        "authlib",
        "cryptography",
        "hashlib",
        "hmac",
        "base64",  # decoding a JWT payload segment
    }
    offenders = sorted(imported & crypto_or_jwt)
    assert offenders == [], (
        "auth.py must not perform in-app token verification; "
        f"found crypto/JWT imports: {offenders}"
    )


def test_auth_module_never_decodes_or_verifies_tokens():
    """No token-decoding/verification call names appear in app-side auth.

    Belt-and-suspenders alongside the import check: assert the source contains
    no signature/expiry verification or JWT-decode call, confirming the app
    trusts the edge authorizer (Requirements 1.1, 1.4).
    """
    lowered = inspect.getsource(auth_module).lower()
    forbidden_calls = [
        ".decode(",  # jwt.decode(...) / base64 decode of a segment
        "verify_signature",
        "verify_token",
        "verify_jwt",
        "check_signature",
        "get_unverified",
    ]
    offenders = [call for call in forbidden_calls if call in lowered]
    assert offenders == [], (
        f"auth.py must not decode/verify tokens; found: {offenders}"
    )
