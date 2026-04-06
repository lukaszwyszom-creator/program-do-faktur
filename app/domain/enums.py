from enum import StrEnum


class UserRole(StrEnum):
    OPERATOR = "operator"
    ADMINISTRATOR = "administrator"


class ContractorSource(StrEnum):
    REGON = "regon"
    MANUAL = "manual"
    REGON_WITH_OVERRIDE = "regon_with_override"


class ContractorLookupStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    NOT_FOUND = "not_found"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    READY_FOR_SUBMISSION = "ready_for_submission"
    SENDING = "sending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class InvoicePaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"


class PaymentMatchStatus(StrEnum):
    UNMATCHED = "unmatched"
    MATCHED = "matched"
    PARTIAL = "partial"
    MANUAL_REVIEW = "manual_review"


class PaymentMatchMethod(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class TransmissionStatus(StrEnum):
    QUEUED = "queued"                    # utworzono job, oczekuje na worker
    PROCESSING = "processing"            # worker pobral zadanie i buduje XML
    SUBMITTED = "submitted"              # XML przyjety przez API KSeF, oczekujemy na potwierdzenie
    WAITING_STATUS = "waiting_status"    # polling odpytuje KSeF, wynik jeszcze nieznany
    SUCCESS = "success"                  # KSeF potwierdzil przyjecie faktury (kod 200)
    FAILED_RETRYABLE = "failed_retryable"  # blad przejsciowy, mozna ponowic
    FAILED_PERMANENT = "failed_permanent"  # blad trwaly (blad mapowania, odrzucenie przez KSeF)


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
