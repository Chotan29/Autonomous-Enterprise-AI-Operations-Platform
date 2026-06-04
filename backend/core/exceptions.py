from fastapi import HTTPException, status


class AEAOPException(Exception):
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(AEAOPException):
    def __init__(self, resource: str, resource_id: str = ""):
        msg = f"{resource} not found" if not resource_id else f"{resource} '{resource_id}' not found"
        super().__init__(msg, "NOT_FOUND")


class ValidationError(AEAOPException):
    def __init__(self, message: str):
        super().__init__(message, "VALIDATION_ERROR")


class AuthError(AEAOPException):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, "AUTH_ERROR")


class PermissionError(AEAOPException):
    def __init__(self, action: str = "", resource: str = ""):
        msg = "Permission denied"
        if action and resource:
            msg = f"Permission denied: cannot '{action}' on '{resource}'"
        super().__init__(msg, "PERMISSION_DENIED")


class DeviceConnectionError(AEAOPException):
    def __init__(self, host: str, reason: str = ""):
        msg = f"Cannot connect to device {host}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, "DEVICE_CONNECTION_ERROR")


class AIServiceError(AEAOPException):
    def __init__(self, message: str):
        super().__init__(message, "AI_SERVICE_ERROR")


class HealingError(AEAOPException):
    def __init__(self, message: str):
        super().__init__(message, "HEALING_ERROR")


class ConflictError(AEAOPException):
    def __init__(self, message: str):
        super().__init__(message, "CONFLICT")


# ── HTTP Exception helpers ────────────────────────────────────────────────────

def http_not_found(resource: str, resource_id: str = "") -> HTTPException:
    msg = f"{resource} not found"
    if resource_id:
        msg = f"{resource} '{resource_id}' not found"
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)


def http_bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def http_forbidden(message: str = "Permission denied") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def http_conflict(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def http_service_unavailable(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=message)
