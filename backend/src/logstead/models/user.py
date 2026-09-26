"""User identity model.

Identity is owned by Cognito. Logstead stores no password and performs no
token parsing; ``UserContext`` simply carries the verified claims that
API Gateway's JWT authorizer placed on the request context (Requirement 1.5,
1.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserContext:
    """The authenticated user, derived from verified Cognito claims.

    Attributes:
        user_id: The Cognito ``sub`` claim — the stable user identifier used
            to key the user's data.
        username: The ``cognito:username`` or email claim, when present.
        claims: The remaining verified token claims.
    """

    user_id: str
    username: str | None = None
    claims: dict = field(default_factory=dict)
