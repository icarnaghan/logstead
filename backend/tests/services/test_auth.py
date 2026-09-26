"""Smoke test for the Auth component happy path (Requirements 1.5, 1.6).

Full claim-extraction edge cases and identity-gating are covered by tasks
5.2 and 5.3; this only exercises the happy path for a well-formed HTTP API
JWT authorizer request context.
"""

from __future__ import annotations

import pytest

from logstead.services.auth import AuthError, current_user, user_id_of


def _http_api_event(claims: dict) -> dict:
    """Build an API Gateway HTTP API proxy event with JWT authorizer claims."""
    return {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}


def test_current_user_reads_verified_claims_happy_path() -> None:
    event = _http_api_event(
        {
            "sub": "user-abc-123",
            "cognito:username": "landlord",
            "email": "owner@example.com",
            "token_use": "id",
        }
    )

    user = current_user(event)

    # sub becomes the stable user id used to scope data.
    assert user.user_id == "user-abc-123"
    # username resolves from cognito:username ahead of email.
    assert user.username == "landlord"
    # remaining verified claims pass through; consumed claims do not.
    assert user.claims == {"email": "owner@example.com", "token_use": "id"}
    # the scoping helper returns the same user id.
    assert user_id_of(user) == "user-abc-123"


# --- Missing / malformed request context (Requirement 1.6) -------------------


@pytest.mark.parametrize(
    "event",
    [
        None,  # non-dict event
        "not-a-dict",
        42,
        {},  # no requestContext at all
        {"requestContext": None},
        {"requestContext": "nope"},
        {"requestContext": {}},  # no authorizer
        {"requestContext": {"authorizer": None}},
        {"requestContext": {"authorizer": "nope"}},
        {"requestContext": {"authorizer": {}}},  # no jwt block
        {"requestContext": {"authorizer": {"jwt": None}}},
        {"requestContext": {"authorizer": {"jwt": "nope"}}},
        {"requestContext": {"authorizer": {"jwt": {}}}},  # no claims
        {"requestContext": {"authorizer": {"jwt": {"claims": None}}}},
        {"requestContext": {"authorizer": {"jwt": {"claims": "nope"}}}},
    ],
)
def test_current_user_rejects_missing_or_malformed_context(event: object) -> None:
    with pytest.raises(AuthError):
        current_user(event)


# --- Missing / invalid subject (sub) -----------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        {"cognito:username": "landlord"},  # sub missing
        {"sub": "", "cognito:username": "landlord"},  # blank sub
        {"sub": None},  # non-string sub
        {"sub": 12345},  # non-string sub
        {"sub": ["user-1"]},  # non-string sub
    ],
)
def test_current_user_rejects_missing_or_invalid_sub(claims: dict) -> None:
    with pytest.raises(AuthError):
        current_user(_http_api_event(claims))


# --- Username fallback ordering ----------------------------------------------


def test_username_prefers_cognito_username() -> None:
    event = _http_api_event(
        {
            "sub": "user-1",
            "cognito:username": "landlord",
            "username": "fallback-user",
            "email": "owner@example.com",
        }
    )

    user = current_user(event)

    assert user.username == "landlord"


def test_username_falls_back_to_username_claim() -> None:
    event = _http_api_event(
        {
            "sub": "user-1",
            "username": "fallback-user",
            "email": "owner@example.com",
        }
    )

    user = current_user(event)

    assert user.username == "fallback-user"


def test_username_falls_back_to_email() -> None:
    event = _http_api_event({"sub": "user-1", "email": "owner@example.com"})

    user = current_user(event)

    assert user.username == "owner@example.com"


def test_username_is_none_when_no_username_claims_present() -> None:
    event = _http_api_event({"sub": "user-1", "token_use": "id"})

    user = current_user(event)

    assert user.username is None


def test_blank_username_claims_are_skipped_in_fallback_order() -> None:
    # Blank (empty-string) values should not win; resolution continues.
    event = _http_api_event(
        {
            "sub": "user-1",
            "cognito:username": "",
            "username": "",
            "email": "owner@example.com",
        }
    )

    user = current_user(event)

    assert user.username == "owner@example.com"


# --- Claims passthrough -------------------------------------------------------


def test_email_remains_on_claims_even_when_used_as_username() -> None:
    event = _http_api_event({"sub": "user-1", "email": "owner@example.com"})

    user = current_user(event)

    # email served as the username fallback but is genuine profile data, so it
    # is NOT consumed — it stays on the passthrough claims.
    assert user.username == "owner@example.com"
    assert user.claims == {"email": "owner@example.com"}


def test_consumed_identity_claims_do_not_leak_to_passthrough() -> None:
    event = _http_api_event(
        {
            "sub": "user-1",
            "cognito:username": "landlord",
            "username": "alias",
            "email": "owner@example.com",
            "token_use": "id",
            "iss": "https://cognito.example.com/pool",
        }
    )

    user = current_user(event)

    # sub / cognito:username / username are consumed; email + extras pass through.
    assert user.claims == {
        "email": "owner@example.com",
        "token_use": "id",
        "iss": "https://cognito.example.com/pool",
    }
    assert "sub" not in user.claims
    assert "cognito:username" not in user.claims
    assert "username" not in user.claims


def test_passthrough_is_empty_when_only_consumed_claims_present() -> None:
    event = _http_api_event({"sub": "user-1", "cognito:username": "landlord"})

    user = current_user(event)

    assert user.user_id == "user-1"
    assert user.username == "landlord"
    assert user.claims == {}
