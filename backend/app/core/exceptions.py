"""
GS-Prep Backend — Exception Handlers

Custom exception classes and FastAPI exception handler registrations.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class GSPrepException(Exception):
    """Base exception for all GS-Prep application errors."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class FileNotFoundError(GSPrepException):
    """Raised when a requested file or resource is not found."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message=message, status_code=404)


class FileTooLargeError(GSPrepException):
    """Raised when an uploaded file exceeds the size limit."""

    def __init__(self, message: str = "File exceeds maximum allowed size"):
        super().__init__(message=message, status_code=413)


class InvalidFileTypeError(GSPrepException):
    """Raised when an uploaded file has an unsupported format."""

    def __init__(self, message: str = "Unsupported file type"):
        super().__init__(message=message, status_code=415)


class ProcessingError(GSPrepException):
    """Raised when a processing module encounters an error."""

    def __init__(self, message: str = "Processing failed"):
        super().__init__(message=message, status_code=500)


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register custom exception handlers with the FastAPI application.

    Args:
        app: The FastAPI application instance.
    """

    @app.exception_handler(GSPrepException)
    async def gsprep_exception_handler(
        request: Request, exc: GSPrepException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": True,
                "message": exc.message,
                "status_code": exc.status_code,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "message": "An unexpected error occurred",
                "status_code": 500,
            },
        )
