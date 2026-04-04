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
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TransmissionStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUBMITTED = "submitted"
    WAITING_STATUS = "waiting_status"
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
