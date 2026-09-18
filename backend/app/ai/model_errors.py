"""Small, focused exception hierarchy for the model abstraction layer.

Future provider implementations translate low-level failures (HTTP errors,
GPU/queue errors, malformed payloads, ...) into these predictable types.
No FastAPI dependency here — a future API layer translates these to HTTP
responses, not the other way around.
"""


class ModelError(Exception):
    """Base class for all model-layer errors."""


class ModelConfigurationError(ModelError):
    """The model layer itself is misconfigured: unknown alias, no default
    alias set, duplicate registration — not a provider-side failure."""


class ModelRequestError(ModelError):
    """The provider rejected the request itself (e.g. invalid parameters
    from the provider's point of view)."""


class ModelTimeoutError(ModelError):
    """The model call did not complete within the expected time."""


class ModelUnavailableError(ModelError):
    """The provider/model is currently unreachable or unavailable."""


class ModelResponseError(ModelError):
    """The provider returned something that couldn't be turned into a
    valid ModelResponse (e.g. a malformed payload)."""
