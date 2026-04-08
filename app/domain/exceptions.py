from app.core.exceptions import AppError


class InvalidInvoiceError(AppError):
    status_code = 422
    code = "invalid_invoice"


class NoKSeFSessionError(InvalidInvoiceError):
    """Brak aktywnej sesji KSeF — faktura nie może zostać wysłana."""
    code = "no_ksef_session"


class InvalidStatusTransitionError(AppError):
    status_code = 409
    code = "invalid_status_transition"
