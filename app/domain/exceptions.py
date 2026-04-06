from app.core.exceptions import AppError


class InvalidInvoiceError(AppError):
    status_code = 422
    code = "invalid_invoice"


class InvalidStatusTransitionError(AppError):
    status_code = 409
    code = "invalid_status_transition"
