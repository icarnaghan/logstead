"""Auth component: read the verified Cognito identity from the request.

Authentication is delegated entirely to Amazon Cognito. API Gateway's native
JWT authorizer validates the Cognito token at the edge (issuer, audience,
signature, expiry) and places the verified subject and claims on the request
context. This module performs **no** token parsing, signature checking, or
password logic of any kind (Requirement 1.5) — it only reads the claims the
authorizer already verified and shapes them into a :class:`UserContext` that
services use to scope data to the authenticated user (Requirement 1.6).

For an API Gateway **HTTP API** with a JWT authorizer, the verified claims are
placed at ``event["requestContext"]["authorizer"]["jwt"]["claims"]``.
"""

from __future__ import annotations

from typing import Any

from logstead.models.user import UserContext

# Username is resolved from these claim names, in priority order. Cognito
# populates ``cognito:username`` on ID tokens; ``username`` and ``email`` are
# common fallbacks depending on the pool/token configuration.
_USERNAME_CLAIMS: tuple[str, ...] = ("cognito:username", "username", "email")

# Claims consumed into dedicated UserContext fields; the remainder pass through
# on ``UserContext.claims``. ``sub`` becomes ``user_id`` and the pure identity
# aliases become ``username``. ``email`` is intentionally NOT consumed even
# though it can serve as a username fallback — it is genuine profile data that
# callers may still need on ``claims``.
_CONSUMED_CLAIMS: frozenset[str] = frozenset({"sub", "cognito:username", "username"})


class AuthError(Exception):
    """Raised when the request carries no verified identity.

    This signals the router to reject the request with ``401 Unauthorized``.
    It is raised only when the authorizer-populated claims are missing or
    malformed (for example, no request context, no authorizer block, or a
    missing ``sub``). A well-formed authorizer context always yields a
    :class:`UserContext`; a missing one is never silently turned into a
    fabricated identity.
    """


def _extract_claims(event: Any) -> dict[str, Any]:
    """Pull the verified claim map out of the HTTP API request context.

    Returns the claims dict for a well-formed HTTP API JWT authorizer context.

    Raises:
        AuthError: If the event/request-context structure is missing or not
            shaped like an HTTP API JWT authorizer context.
    """
    if not isinstance(event, dict):
        raise AuthError("Missing request context")

    request_context = event.get("requestContext")
    if not isinstance(request_context, dict):
        raise AuthError("Missing request context")

    authorizer = request_context.get("authorizer")
    if not isinstance(authorizer, dict):
        raise AuthError("Missing authorizer context")

    # HTTP API JWT authorizer nests claims under a "jwt" block.
    jwt_block = authorizer.get("jwt")
    if not isinstance(jwt_block, dict):
        raise AuthError("Missing verified JWT claims")

    claims = jwt_block.get("claims")
    if not isinstance(claims, dict):
        raise AuthError("Missing verified JWT claims")

    return claims


def current_user(event: Any) -> UserContext:
    """Resolve the authenticated user from the API Gateway request context.

    Reads the verified Cognito ``sub`` and claims that API Gateway's JWT
    authorizer placed on the request context. No token parsing or signature
    checking happens here — validation already occurred at the edge.

    The Cognito ``sub`` claim becomes :attr:`UserContext.user_id` (the stable
    key for the user's data). ``username`` is resolved from
    ``cognito:username``/``username``/``email`` in that order. Every remaining
    verified claim passes through on :attr:`UserContext.claims`.

    Args:
        event: The API Gateway HTTP API proxy event (a dict).

    Returns:
        The authenticated :class:`UserContext`.

    Raises:
        AuthError: If no verified identity is present, so the router can
            reject the request with ``401 Unauthorized`` without fabricating
            an identity.
    """
    claims = _extract_claims(event)

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AuthError("Verified claims are missing the subject (sub)")

    username: str | None = None
    for claim_name in _USERNAME_CLAIMS:
        value = claims.get(claim_name)
        if isinstance(value, str) and value:
            username = value
            break

    passthrough = {
        key: value for key, value in claims.items() if key not in _CONSUMED_CLAIMS
    }

    return UserContext(user_id=sub, username=username, claims=passthrough)


def user_id_of(user: UserContext) -> str:
    """Return the authenticated user id used to scope data.

    Services call this to obtain the stable Cognito ``sub`` that partitions a
    user's data in the repository (Requirement 1.6), rather than reaching into
    :class:`UserContext` internals directly.
    """
    return user.user_id
