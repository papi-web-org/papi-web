from typing_extensions import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.option import Option


class SharlyChessException(Exception):
    def __init__(self, string: str):
        super().__init__(string)


class DatabaseInaccessibleException(SharlyChessException):
    """Error raised when a database file exists but cannot be opened
    (locked by another program, file sync such as OneDrive, permissions…)."""


class DictReaderException(SharlyChessException):
    """Error raised when validating the content of a dict."""

    def __init__(self, path: list[str], message: str):
        log_prefix = '.'.join(path) + ' - ' if path else ''
        super().__init__(log_prefix + message)


class ImporterError(SharlyChessException):
    """Error raised validating a data import."""


class PairingEngineError(SharlyChessException):
    """Error raised when the pairing engine fails to produce pairings.

    *detail* is the engine's own diagnostic (its stderr/stdout), phrased for
    the operator and safe to surface in the UI. The full exception message
    still carries the internal context for the logs."""

    def __init__(self, message: str, detail: str):
        super().__init__(message)
        self.detail = detail


class OptionError(SharlyChessException):
    """Error raised when validating an option."""

    def __init__(self, message: str, option: 'Option'):
        super().__init__(message)
        self.option = option


class FormError(SharlyChessException):
    """Error raised when validating a form value."""
