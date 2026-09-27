"""Provider persistence errors."""


class ProviderRunPersistenceError(RuntimeError):
    """Raised when provider persistence input or stored state is invalid."""


class ProviderRunConflictError(ProviderRunPersistenceError):
    """Raised when provider state conflicts with a requested mutation."""


class ProviderRunTransitionError(ProviderRunPersistenceError):
    """Raised when a provider run transition is illegal."""
