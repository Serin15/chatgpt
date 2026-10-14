class ProviderError(Exception):
    """A sanitized, user-safe upstream failure; never include credentials or raw URLs."""
