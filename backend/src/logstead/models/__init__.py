"""Domain data models for Logstead.

This package defines the domain dataclasses used across the application
services, repository, and router layers. Money fields are typed as
``decimal.Decimal`` throughout (stored as two-decimal strings in DynamoDB).
"""

from logstead.models.result import Error, Ok, Result
from logstead.models.user import UserContext
from logstead.models.property import (
    AddressSuggestion,
    Property,
    PropertyDetails,
    PropertyFeatures,
    PropertyInput,
    PropertyPhoto,
    PropertyUsageYear,
)
from logstead.models.business import (
    DEFAULT_TAX_YEAR_END,
    ENTITY_TYPES,
    Business,
    BusinessDocument,
    BusinessInput,
)
from logstead.models.category import CategoryKind, ScheduleECategory
from logstead.models.transaction import (
    Document,
    Transaction,
    TransactionInput,
    TransactionType,
)
from logstead.models.depreciation import (
    AssetInput,
    DepreciableAsset,
    DepreciationScheduleRow,
)
from logstead.models.imports import DraftTransaction, ImportSession, ImportStatus
from logstead.models.schedule_e_import import (
    EntryOutcome,
    ImportOutcome,
    ImportSubmission,
    LineAmountInput,
    PropertyEntryInput,
    RemoveOutcome,
)
from logstead.models.schedule_e_extraction import (
    CompleteOutcome,
    ExtractedColumn,
    ExtractedLine,
    ExtractionJobView,
    JobStatus,
    ReviewDraft,
    StartExtractionOutcome,
)
from logstead.models.loan import (
    MAX_MONEY,
    Loan,
    LoanInput,
    LoanSchedule,
    LoanView,
    PaymentRow,
    YearlyRollup,
    YearlyRollupView,
)

__all__ = [
    # Result wrapper
    "Result",
    "Ok",
    "Error",
    # User
    "UserContext",
    # Property
    "PropertyInput",
    "Property",
    "PropertyDetails",
    "PropertyFeatures",
    "PropertyUsageYear",
    "PropertyPhoto",
    "AddressSuggestion",
    # Business
    "BusinessInput",
    "Business",
    "BusinessDocument",
    "ENTITY_TYPES",
    "DEFAULT_TAX_YEAR_END",
    # Category
    "ScheduleECategory",
    "CategoryKind",
    # Transaction
    "TransactionInput",
    "Transaction",
    "TransactionType",
    "Document",
    # Depreciation
    "AssetInput",
    "DepreciableAsset",
    "DepreciationScheduleRow",
    # Import
    "ImportSession",
    "ImportStatus",
    "DraftTransaction",
    # Schedule E import
    "LineAmountInput",
    "PropertyEntryInput",
    "ImportSubmission",
    "EntryOutcome",
    "ImportOutcome",
    "RemoveOutcome",
    # Schedule E extraction
    "JobStatus",
    "CompleteOutcome",
    "StartExtractionOutcome",
    "ExtractedLine",
    "ExtractedColumn",
    "ReviewDraft",
    "ExtractionJobView",
    # Loan
    "MAX_MONEY",
    "LoanInput",
    "Loan",
    "PaymentRow",
    "YearlyRollup",
    "LoanView",
    "YearlyRollupView",
    "LoanSchedule",
]
