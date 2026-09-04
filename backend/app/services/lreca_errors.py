"""Stable API-facing failures from the isolated LRECA runtime."""

LRECA_READY_MESSAGE = "Human-specific LRECA is loaded and ready."
LRECA_UNAVAILABLE_MESSAGE = "LRECA is unavailable. Please retry when the service is ready."
LRECA_TIMEOUT_MESSAGE = "LRECA analysis exceeded the configured time limit."
LRECA_ANALYSIS_FAILED_MESSAGE = "LRECA could not complete the analysis."


class LRECAUnavailableError(RuntimeError):
    """The model did not load or its worker is no longer running."""


class LRECATimeoutError(RuntimeError):
    """A startup or inference operation exceeded its configured time limit."""


class LRECAAnalysisError(RuntimeError):
    """A loaded worker could not compute or validate the requested result."""
