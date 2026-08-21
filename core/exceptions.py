from rest_framework.views import exception_handler
from rest_framework.response import Response


class DomainError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    message = "Internal server error."

    def __init__(self, message=None, details=None):
        super().__init__(message or self.message)
        self.details = details or {}


class ValidationError(DomainError):
    status_code = 400
    code = "VALIDATION_ERROR"
    message = "Validation error."


class NotFoundError(DomainError):
    status_code = 404
    code = "NOT_FOUND"
    message = "Resource not found."


class ConflictError(DomainError):
    status_code = 409
    code = "CONFLICT"
    message = "Resource conflict."


class ForbiddenError(DomainError):
    status_code = 403
    code = "FORBIDDEN"
    message = "Access denied."


class K8sUnavailableError(DomainError):
    status_code = 502
    code = "KUBERNETES_UNAVAILABLE"
    message = "Cannot communicate with Kubernetes."


class K8sConflictError(ConflictError):
    code = "KUBERNETES_CONFLICT"
    message = "Resource already exists in Kubernetes."


class K8sForbiddenError(ForbiddenError):
    code = "KUBERNETES_FORBIDDEN"
    message = "Kubernetes denied access."


def _format_drf_detail(detail):
    if isinstance(detail, dict):
        if "detail" in detail:
            message = str(detail["detail"])
        else:
            message = "Request failed."
        details = detail
    elif isinstance(detail, list):
        message = "Validation error."
        details = detail
    else:
        message = str(detail)
        details = {"detail": str(detail)}

    return message, details


def domain_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                }
            },
            status=exc.status_code,
        )

    response = exception_handler(exc, context)

    if response is not None:
        status = response.status_code

        if status == 400:
            code = "VALIDATION_ERROR"
        elif status == 401:
            code = "UNAUTHORIZED"
        elif status == 403:
            code = "FORBIDDEN"
        elif status == 404:
            code = "NOT_FOUND"
        elif status == 409:
            code = "CONFLICT"
        else:
            code = "HTTP_ERROR"

        message, details = _format_drf_detail(response.data)

        response.data = {
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        }

    return response