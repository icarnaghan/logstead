"""DynamoDB single-table key scheme for Logstead.

This module is the single source of truth for the primary-key (PK/SK) and
secondary-index (GSI1PK/GSI1SK, GSI2PK/GSI2SK) conventions of the ``Logstead``
table. Services never build raw keys; they call the helpers here so the key
scheme stays encapsulated (design: "repositories encapsulate the key scheme so
services never build keys directly").

Conventions (see design.md "Single-table key design"):

    User                    PK=USER#<userId>        SK=PROFILE
    Property (user view)    PK=USER#<userId>        SK=PROP#<propertyId>
    Property (meta mirror)  PK=PROPERTY#<id>        SK=META
    PropertyDetails         PK=PROPERTY#<id>        SK=DETAILS
    PropertyUsageYear       PK=PROPERTY#<id>        SK=USAGE#<taxYear>
    PropertyPhoto           PK=PROPERTY#<id>        SK=PHOTO#<photoId>
    Business (user view)    PK=USER#<userId>        SK=BUSINESS#<businessId>
    Business (meta mirror)  PK=BUSINESS#<id>        SK=META
    BusinessDocument        PK=BUSINESS#<id>        SK=DOC#<documentId>
    ScheduleECategory       PK=CATEGORY#<catId>     SK=META
    Transaction             PK=PROPERTY#<id>        SK=TXN#<invDate>#<txnId>
    Document (receipt)      PK=PROPERTY#<id>        SK=TXN#<invDate>#<txnId>#DOC#<docId>
    DepreciableAsset        PK=PROPERTY#<id>        SK=ASSET#<assetId>
    DepreciationScheduleRow PK=PROPERTY#<id>        SK=ASSET#<assetId>#SCHED#<taxYear>
    Loan                    PK=PROPERTY#<id>        SK=LOAN#<loanId>
    LoanYearRollup          PK=PROPERTY#<id>        SK=LOAN#<loanId>#YEAR#<taxYear>
    ImportSession           PK=IMPORT#<sessionId>   SK=META
    DraftTransaction        PK=IMPORT#<sessionId>   SK=DRAFT#<draftId>
    Extraction_Job          PK=USER#<userId>        SK=SEEXTRACT#<jobId>
    Package_Job             PK=USER#<userId>        SK=ACCTPKG#<jobId>

Global secondary indexes:

    GSI1  reverse / cross-cutting lookups
          Property        GSI1PK=USER#<userId>       GSI1SK=PROP#<propertyId>
          ImportSession   GSI1PK=PROPERTY#<id>       GSI1SK=IMPORT#<sessionId>
    GSI2  tax-year-scoped access for a property
          Transaction     GSI2PK=PROPERTY#<id>#YEAR#<taxYear>  GSI2SK=TXN#<invDate>#<txnId>
          ScheduleRow     GSI2PK=PROPERTY#<id>#YEAR#<taxYear>  GSI2SK=SCHED#<assetId>
          LoanYearRollup  GSI2PK=PROPERTY#<id>#YEAR#<taxYear>  GSI2SK=LOANYR#<loanId>

Inverted-date encoding (design.md "Date-descending ordering"):
    invDate = 99999999 - YYYYMMDD
DynamoDB returns items in ascending sort-key order, so encoding the inverted
date makes a natural ascending scan yield most-recent-first (Requirement 5.4).
The GSI2 sort key reuses the inverted-date form so tax-year-scoped results are
likewise date-descending (Requirement 5.5).

Standard library only; no boto3 or third-party imports.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

# --- Key prefixes / constants ------------------------------------------------

USER_PREFIX = "USER#"
PROPERTY_PREFIX = "PROPERTY#"
PROP_PREFIX = "PROP#"
BUSINESS_PREFIX = "BUSINESS#"
USAGE_PREFIX = "USAGE#"
PHOTO_PREFIX = "PHOTO#"
CATEGORY_PREFIX = "CATEGORY#"
TXN_PREFIX = "TXN#"
DOC_PREFIX = "DOC#"
ASSET_PREFIX = "ASSET#"
SCHED_PREFIX = "SCHED#"
IMPORT_PREFIX = "IMPORT#"
DRAFT_PREFIX = "DRAFT#"
SEEXTRACT_PREFIX = "SEEXTRACT#"
PACKAGE_JOB_PREFIX = "ACCTPKG#"
ACT_PREFIX = "ACT#"
YEAR_PREFIX = "YEAR#"
PLCF_PREFIX = "PLCF#"
LOAN_PREFIX = "LOAN#"
LOAN_YEAR_MARKER = "#YEAR#"  # separates loan id from tax year inside a rollup SK
GSI2_LOAN_YEAR_PREFIX = "LOANYR#"

PROFILE_SK = "PROFILE"
META_SK = "META"
DETAILS_SK = "DETAILS"
NOTE_SK = "NOTE"
PLCF_OPENING_SK = "PLCF_OPENING"

# Largest 8-digit YYYYMMDD (9999-12-31); used to invert dates for descending
# sort order. invDate = INVERT_BASE - YYYYMMDD.
INVERT_BASE = 99999999

# Zero-padded width of a YYYYMMDD / inverted-date token, so string sort order
# matches numeric order.
_DATE_WIDTH = 8


# --- Inverted-date encoding --------------------------------------------------

def to_yyyymmdd(d: date) -> int:
    """Return the integer ``YYYYMMDD`` form of a date (e.g. 2024-03-07 -> 20240307)."""
    return d.year * 10000 + d.month * 100 + d.day


def from_yyyymmdd(value: int) -> date:
    """Inverse of :func:`to_yyyymmdd`: parse an integer ``YYYYMMDD`` into a date."""
    year, rem = divmod(int(value), 10000)
    month, day = divmod(rem, 100)
    return date(year, month, day)


def inverted_date(d: date) -> str:
    """Encode a date as the zero-padded inverted-date token used in sort keys.

    ``invDate = 99999999 - YYYYMMDD``. A newer date produces a *smaller* token,
    so ascending DynamoDB sort-key order yields newest-first.
    """
    inv = INVERT_BASE - to_yyyymmdd(d)
    return f"{inv:0{_DATE_WIDTH}d}"


def date_from_inverted(token: str | int) -> date:
    """Inverse of :func:`inverted_date`: recover the original date from a token."""
    inv = int(token)
    return from_yyyymmdd(INVERT_BASE - inv)


# --- User --------------------------------------------------------------------

def user_pk(user_id: str) -> str:
    return f"{USER_PREFIX}{user_id}"


def user_profile_sk() -> str:
    return PROFILE_SK


# --- Property ----------------------------------------------------------------

def property_scoped_pk(property_id: str) -> str:
    """PK for a property's child items (details, usage, photos, txns, assets)."""
    return f"{PROPERTY_PREFIX}{property_id}"


def property_meta_sk() -> str:
    """SK of the mirrored ``PROPERTY#<id> / META`` item."""
    return META_SK


def property_user_sk(property_id: str) -> str:
    """SK of the ``USER#<id> / PROP#<propertyId>`` list item."""
    return f"{PROP_PREFIX}{property_id}"


def property_list_prefix() -> str:
    """SK ``begins_with`` prefix to list a user's properties."""
    return PROP_PREFIX


def property_details_sk() -> str:
    return DETAILS_SK


def property_note_sk() -> str:
    """SK of the single per-property free-text note item (``PROPERTY#<id> / NOTE``)."""
    return NOTE_SK


# --- Property usage year -----------------------------------------------------

def usage_sk(tax_year: int) -> str:
    return f"{USAGE_PREFIX}{tax_year}"


# --- Passive loss carryforward -----------------------------------------------

def plcf_year_sk(tax_year: int) -> str:
    """SK ``PLCF#<taxYear>`` for one per-year carryforward entry."""
    return f"{PLCF_PREFIX}{tax_year}"


def plcf_list_prefix() -> str:
    """SK ``begins_with`` prefix to list a user's carryforward entries."""
    return PLCF_PREFIX


def plcf_opening_sk() -> str:
    """SK of the single per-user opening-balance item (``USER#<id> / PLCF_OPENING``)."""
    return PLCF_OPENING_SK


# --- Property photo ----------------------------------------------------------

def photo_sk(photo_id: str) -> str:
    return f"{PHOTO_PREFIX}{photo_id}"


def photo_list_prefix() -> str:
    return PHOTO_PREFIX


# --- Business ----------------------------------------------------------------

def business_scoped_pk(business_id: str) -> str:
    """PK for a business's child items (meta mirror, documents)."""
    return f"{BUSINESS_PREFIX}{business_id}"


def business_meta_sk() -> str:
    """SK of the mirrored ``BUSINESS#<id> / META`` item."""
    return META_SK


def business_user_sk(business_id: str) -> str:
    """SK of the ``USER#<id> / BUSINESS#<businessId>`` list item."""
    return f"{BUSINESS_PREFIX}{business_id}"


def business_list_prefix() -> str:
    """SK ``begins_with`` prefix to list a user's businesses."""
    return BUSINESS_PREFIX


def business_document_sk(document_id: str) -> str:
    """SK ``BUSINESS#<id> / DOC#<documentId>`` for one business document."""
    return f"{DOC_PREFIX}{document_id}"


def business_document_list_prefix() -> str:
    """SK ``begins_with`` prefix to list a business's documents."""
    return DOC_PREFIX


# --- Schedule E category (reference data) ------------------------------------

def category_pk(category_id: str) -> str:
    return f"{CATEGORY_PREFIX}{category_id}"


def category_sk() -> str:
    return META_SK


# --- Transaction -------------------------------------------------------------

def transaction_sk(d: date, txn_id: str) -> str:
    """SK ``TXN#<invDate>#<txnId>`` (inverted-date encoded for date-desc order)."""
    return f"{TXN_PREFIX}{inverted_date(d)}#{txn_id}"


def transaction_list_prefix() -> str:
    """SK ``begins_with`` prefix to list a property's transactions, newest first."""
    return TXN_PREFIX


# --- Document (receipt attached to a transaction) ----------------------------

def document_sk(d: date, txn_id: str, doc_id: str) -> str:
    """SK ``TXN#<invDate>#<txnId>#DOC#<docId>`` — co-located under its transaction."""
    return f"{transaction_sk(d, txn_id)}#{DOC_PREFIX}{doc_id}"


# --- Depreciable asset -------------------------------------------------------

def asset_sk(asset_id: str) -> str:
    return f"{ASSET_PREFIX}{asset_id}"


def asset_list_prefix() -> str:
    """SK ``begins_with`` prefix to list assets (filter out ``#SCHED#`` rows)."""
    return ASSET_PREFIX


def schedule_row_sk(asset_id: str, tax_year: int) -> str:
    """SK ``ASSET#<assetId>#SCHED#<taxYear>`` for one depreciation schedule row."""
    return f"{ASSET_PREFIX}{asset_id}#{SCHED_PREFIX}{tax_year}"


def schedule_list_prefix(asset_id: str) -> str:
    """SK ``begins_with`` prefix for all schedule rows of one asset."""
    return f"{ASSET_PREFIX}{asset_id}#{SCHED_PREFIX}"


# --- Loan / loan year rollup -------------------------------------------------

def loan_sk(loan_id: str) -> str:
    """SK ``LOAN#<loanId>`` for a loan under ``PROPERTY#<id>``."""
    return f"{LOAN_PREFIX}{loan_id}"


def loan_list_prefix() -> str:
    """SK ``begins_with`` prefix to list loans (filter out rollups with :func:`is_loan_year_sk`)."""
    return LOAN_PREFIX


def loan_year_sk(loan_id: str, tax_year: int) -> str:
    """SK ``LOAN#<loanId>#YEAR#<taxYear>`` for one yearly rollup row."""
    return f"{LOAN_PREFIX}{loan_id}{LOAN_YEAR_MARKER}{tax_year}"


def loan_year_list_prefix(loan_id: str) -> str:
    """SK ``begins_with`` prefix for all rollup rows of one loan."""
    return f"{LOAN_PREFIX}{loan_id}{LOAN_YEAR_MARKER}"


def is_loan_year_sk(sk: str) -> bool:
    """True when ``sk`` is a loan rollup SK (``LOAN#<id>#YEAR#<year>``)."""
    return sk.startswith(LOAN_PREFIX) and LOAN_YEAR_MARKER in sk


# --- Import session / draft transaction --------------------------------------

def import_pk(import_session_id: str) -> str:
    return f"{IMPORT_PREFIX}{import_session_id}"


def import_meta_sk() -> str:
    return META_SK


def draft_sk(draft_id: str) -> str:
    return f"{DRAFT_PREFIX}{draft_id}"


def draft_list_prefix() -> str:
    """SK ``begins_with`` prefix to list drafts for an import session."""
    return DRAFT_PREFIX


# --- Schedule E extraction job (transient, TTL'd, per-user) ------------------

def extraction_job_sk(job_id: str) -> str:
    """SK ``SEEXTRACT#<jobId>`` for a transient Schedule E extraction job.

    Keyed under the owning ``USER#<userId>`` partition. The ``SEEXTRACT#``
    prefix is deliberately distinct from the expense feature's ``IMPORT#`` /
    ``DRAFT#`` keys so the two features share no storage keys (design.md
    "Distinct storage keys", Req 13.2).
    """
    return f"{SEEXTRACT_PREFIX}{job_id}"


def extraction_job_list_prefix() -> str:
    """SK ``begins_with`` prefix to list a user's extraction jobs."""
    return SEEXTRACT_PREFIX


# --- Accountant package job (transient, TTL'd, per-user) ---------------------


def package_job_sk(job_id: str) -> str:
    """SK ``ACCTPKG#<jobId>`` for a transient accountant package job.

    Keyed under the owning ``USER#<userId>`` partition.
    """
    return f"{PACKAGE_JOB_PREFIX}{job_id}"


# --- Activity event (TTL'd, per-user) ----------------------------------------

#: Largest 14-digit value; inverted epoch milliseconds = this - epoch_ms.
ACTIVITY_INVERT_BASE = 99999999999999


def activity_sk(at: datetime, event_id: str) -> str:
    """SK ``ACT#<14-digit inverted ms>#<eventId>`` under ``USER#<userId>``.

    A later ``at`` gives a smaller token, so an ascending scan is newest first.
    """
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    epoch_ms = int(at.timestamp() * 1000)
    return f"{ACT_PREFIX}{ACTIVITY_INVERT_BASE - epoch_ms:014d}#{event_id}"


def activity_list_prefix() -> str:
    """SK ``begins_with`` prefix to list a user's activity events."""
    return ACT_PREFIX


def activity_gsi1_pk(property_id: str) -> str:
    """GSI1PK ``PROPERTY#<id>`` for a property's activity view."""
    return property_scoped_pk(property_id)


# --- GSI1: reverse / cross-cutting lookups -----------------------------------

def gsi1_property_keys(user_id: str, property_id: str) -> tuple[str, str]:
    """(GSI1PK, GSI1SK) for a property row: list all of a user's properties."""
    return user_pk(user_id), f"{PROP_PREFIX}{property_id}"


def gsi1_import_keys(property_id: str, import_session_id: str) -> tuple[str, str]:
    """(GSI1PK, GSI1SK) for an import session: look up imports by property."""
    return property_scoped_pk(property_id), f"{IMPORT_PREFIX}{import_session_id}"


# --- GSI2: tax-year-scoped access for a property -----------------------------

def gsi2_year_pk(property_id: str, tax_year: int) -> str:
    """GSI2 partition key ``PROPERTY#<id>#YEAR#<taxYear>`` for tax-year scoping."""
    return f"{PROPERTY_PREFIX}{property_id}#{YEAR_PREFIX}{tax_year}"


def gsi2_transaction_sk(d: date, txn_id: str) -> str:
    """GSI2 sort key for a transaction — reuses the inverted-date form."""
    return f"{TXN_PREFIX}{inverted_date(d)}#{txn_id}"


def gsi2_transaction_prefix() -> str:
    """GSI2 SK ``begins_with`` prefix for tax-year transaction queries."""
    return TXN_PREFIX


def gsi2_schedule_sk(asset_id: str) -> str:
    """GSI2 sort key ``SCHED#<assetId>`` for a schedule row within a tax year."""
    return f"{SCHED_PREFIX}{asset_id}"


def gsi2_schedule_prefix() -> str:
    """GSI2 SK ``begins_with`` prefix for tax-year depreciation queries."""
    return SCHED_PREFIX


def gsi2_loan_year_sk(loan_id: str) -> str:
    """GSI2 sort key ``LOANYR#<loanId>`` for a loan rollup within a tax year."""
    return f"{GSI2_LOAN_YEAR_PREFIX}{loan_id}"


def gsi2_loan_year_prefix() -> str:
    """GSI2 SK ``begins_with`` prefix for tax-year loan interest queries."""
    return GSI2_LOAN_YEAR_PREFIX
