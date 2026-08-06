"""Pydantic domain models for invoice processing."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Decision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


class IssueSeverity(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    INFO = "info"


class LineItem(BaseModel):
    name: str
    quantity: float
    unit_price: Optional[float] = None
    line_total: Optional[float] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class ExtractedInvoice(BaseModel):
    vendor: str = ""
    invoice_number: str = ""
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    amount: float = 0.0
    currency: str = "USD"
    items: list[LineItem] = Field(default_factory=list)
    payment_terms: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    anomalies: list[str] = Field(default_factory=list)
    raw_notes: Optional[str] = None

    @field_validator("vendor", "invoice_number", mode="before")
    @classmethod
    def coerce_str(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.HARD
    item: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def hard_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.HARD]

    @property
    def soft_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.SOFT]


class ApprovalResult(BaseModel):
    decision: Decision = Decision.PENDING
    rationale: str = ""
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_scrutiny: bool = False
    critique: Optional[str] = None
    reflections: list[str] = Field(default_factory=list)


class PaymentResult(BaseModel):
    status: str
    vendor: str
    amount: float
    transaction_id: Optional[str] = None
    timestamp: Optional[str] = None
    message: str = ""


class StageLog(BaseModel):
    stage: str
    status: str
    duration_ms: float = 0.0
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class PipelineResult(BaseModel):
    invoice_path: str
    final_status: Decision = Decision.PENDING
    extracted: Optional[ExtractedInvoice] = None
    validation: Optional[ValidationResult] = None
    approval: Optional[ApprovalResult] = None
    payment: Optional[PaymentResult] = None
    stages: list[StageLog] = Field(default_factory=list)
    error: Optional[str] = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "invoice_path": self.invoice_path,
            "final_status": self.final_status.value,
            "vendor": self.extracted.vendor if self.extracted else None,
            "invoice_number": self.extracted.invoice_number if self.extracted else None,
            "amount": self.extracted.amount if self.extracted else None,
            "validation_passed": self.validation.passed if self.validation else None,
            "approval_rationale": self.approval.rationale if self.approval else None,
            "payment_status": self.payment.status if self.payment else None,
            "error": self.error,
        }
