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
]
