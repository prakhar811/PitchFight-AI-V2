"""Application services.

Business logic lives here, above repositories and below routes. Services
own transaction boundaries (commit/rollback); repositories only flush.

TODO: Add pitch/scoring services in later implementation tasks.
"""

from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)
from app.services.simulation_service import (
    InvalidSimulationTransitionError,
    JudgePersonaNotFoundError,
    PitchNotFoundError,
    SimulationNotFoundError,
    SimulationPersistenceError,
    SimulationService,
    SimulationTerminalError,
)

__all__ = [
    "AuthService",
    "EmailAlreadyRegisteredError",
    "InvalidCredentialsError",
    "InvalidSimulationTransitionError",
    "JudgePersonaNotFoundError",
    "PitchNotFoundError",
    "SimulationNotFoundError",
    "SimulationPersistenceError",
    "SimulationService",
    "SimulationTerminalError",
]
