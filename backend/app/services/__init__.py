"""Application services.

Business logic lives here, above repositories and below routes. Services
own transaction boundaries (commit/rollback); repositories only flush.

TODO: Add pitch/simulation/score services in later implementation tasks.
"""

from app.services.auth_service import AuthService, EmailAlreadyRegisteredError, InvalidCredentialsError

__all__ = ["AuthService", "EmailAlreadyRegisteredError", "InvalidCredentialsError"]
