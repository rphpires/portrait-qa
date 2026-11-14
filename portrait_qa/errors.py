"""Errors raised by the engine. Each one carries a stable code and an HTTP status for the API."""


class PortraitQAError(Exception):
    """Base error. ``code`` is stable and meant for client code; ``message`` is for humans."""

    code = "INTERNAL_ERROR"
    status = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidImageError(PortraitQAError):
    """The bytes are not an image OpenCV can decode (or the payload is malformed)."""

    code = "INVALID_IMAGE"
    status = 400


class ImageTooLargeError(PortraitQAError):
    """The upload or the decoded image exceeds the configured limits."""

    code = "IMAGE_TOO_LARGE"
    status = 413


class UnknownProfileError(PortraitQAError):
    code = "UNKNOWN_PROFILE"
    status = 400


class NoFaceError(PortraitQAError):
    """A crop was requested but no face was found."""

    code = "NO_FACE"
    status = 422


class BusyError(PortraitQAError):
    """All workers are busy; the client should retry shortly."""

    code = "BUSY"
    status = 503


class ConfigError(PortraitQAError):
    code = "CONFIG_ERROR"
    status = 500
