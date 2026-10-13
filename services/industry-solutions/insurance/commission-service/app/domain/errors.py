from __future__ import annotations


class CommissionError(Exception):
    """A business-rule rejection carrying the legacy ORA code it replaces."""

    code = "COMMISSION_ERROR"
    ora_code = -20000
    http_status = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidRateError(CommissionError):
    code, ora_code, http_status = "INVALID_RATE", -20001, 422


class UnknownAgentError(CommissionError):
    code, ora_code, http_status = "UNKNOWN_AGENT", -20002, 404


class InactiveAgentError(CommissionError):
    code, ora_code, http_status = "INACTIVE_AGENT", -20003, 409


class UnknownProductError(CommissionError):
    code, ora_code, http_status = "UNKNOWN_PRODUCT", -20004, 404


class UnknownPolicyError(CommissionError):
    code, ora_code, http_status = "UNKNOWN_POLICY", -20005, 404


class BadSplitError(CommissionError):
    code, ora_code, http_status = "BAD_SPLIT", -20006, 422


class NoRateError(CommissionError):
    code, ora_code, http_status = "NO_RATE", -20007, 404


class PolicyNotActiveError(CommissionError):
    code, ora_code, http_status = "POLICY_NOT_ACTIVE", -20008, 409


class DuplicateOpenRateError(CommissionError):
    """Legacy surfaced this as ORA-00001 on UX_RATES_OPEN."""

    code, ora_code, http_status = "DUPLICATE_OPEN_RATE", -1, 409


class ConstraintViolationError(CommissionError):
    """Legacy surfaced this as ORA-02290 (check constraint violated)."""

    code, ora_code, http_status = "CONSTRAINT_VIOLATION", -2290, 422


class InvalidPeriodError(CommissionError):
    """Legacy surfaced this as ORA-01843 / ORA-01861 from TO_DATE."""

    code, http_status = "INVALID_PERIOD", 422

    def __init__(self, message: str, ora_code: int) -> None:
        super().__init__(message)
        self.ora_code = ora_code
