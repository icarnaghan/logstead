"""Property-based test: the Other expense category (Line 19) requires a
description; all other categories treat the description as optional.

Design Property 15 (Requirement 7.4): *for any* transaction assigned the Other
category (Line 19), creation is rejected when the description is blank and
accepted when a non-blank description is present.

``TransactionService.create`` (``services/transaction.py``) resolves the chosen
category and, when ``category.requires_description`` is set (the ``other``
category, Line 19; see ``CATEGORY_CATALOG`` in ``services/category.py``),
requires a non-blank description. The description is trimmed before the check,
so an empty string, a whitespace-only string, and an absent (``None``)
description are all treated as "blank" and rejected with a ``validation`` error
on the ``description`` field. Every non-Other category ignores the description,
so a blank/absent description there still succeeds.

This test drives that invariant universally on two fronts:

* **Other category**: the description is drawn across {non-blank,
  empty-string, whitespace-only, absent}; creation succeeds *iff* the
  description is non-blank (after trimming), otherwise it fails with kind
  ``"validation"`` and ``error.field == "description"``.
* **Non-Other categories**: a sampling of the other catalog categories is
  driven with a blank or absent description; creation still succeeds, and the
  stored description is normalized to ``None``.

All other fields (amount, date, type) are held valid so this property is not
confounded by the amount>0 / required-field rules (Property 7) or the
category-to-line mapping (Property 13).

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(with the GSI2 tax-year index the service relies on) plus an S3 bucket needed to
construct the ``S3FileAdapter``, mirroring the fixture pattern in
``test_transaction.py``. Per-example provisioning is not instantaneous, so the
deadline is disabled; the example count is held at >= 100.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"
# The Other expense category (Line 19) is the single description-requiring
# category in the catalog (Requirement 7.4).
OTHER_CATEGORY_ID = "other"
# A valid amount/date/type held constant so only the description varies.
VALID_AMOUNT = Decimal("1234.56")
VALID_DATE = "2024-03-07"
VALID_TYPE = "expense"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI2) and S3 bucket.

    Yields a :class:`TransactionService` bound to freshly created resources so
    each Hypothesis example runs against a clean store.
    """
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield TransactionService(
            DynamoRepository(ddb, TABLE_NAME), S3FileAdapter(s3, BUCKET)
        )


# --- Description strategy: non-blank / empty / whitespace-only / absent ------
#
# Non-blank descriptions contain at least one non-whitespace character (so they
# survive trimming). Blank descriptions are the empty string, whitespace-only
# strings, and the absent (None) description -- all of which the service treats
# as "no description".
_non_blank_description = st.text(min_size=1, max_size=80).filter(
    lambda s: s.strip() != ""
)
_whitespace_only = st.text(alphabet=" \t\n\r\f\v", min_size=1, max_size=8)
_blank_description = st.one_of(
    st.just(""), _whitespace_only, st.none()
)
_descriptions = st.one_of(_non_blank_description, _blank_description)


def _is_non_blank(description: str | None) -> bool:
    """A description is non-blank iff it has a non-whitespace character."""
    return description is not None and description.strip() != ""


# Non-Other categories: every catalog entry that does not require a description.
_NON_OTHER_CATEGORY_IDS = [
    c.id for c in CATEGORY_CATALOG if not c.requires_description
]


# Feature: logstead, Property 15: Other expenses require a description
@settings(deadline=None, max_examples=200)
@given(description=_descriptions)
def test_other_category_requires_non_blank_description(
    description: str | None,
) -> None:
    """Other-category create succeeds iff a non-blank description is provided.

    Validates: Requirement 7.4
    """
    data = TransactionInput(
        property_id=PROPERTY_ID,
        date=VALID_DATE,
        amount=VALID_AMOUNT,
        type=VALID_TYPE,
        category_id=OTHER_CATEGORY_ID,
        description=description,
    )

    with _moto_service() as service:
        result = service.create(data)

        if _is_non_blank(description):
            # A non-blank description satisfies the Other-category rule.
            assert result.is_ok, (
                f"expected success for Other with description={description!r}"
            )
            txn = result.value
            assert txn.id
            assert txn.category_id == OTHER_CATEGORY_ID
            assert txn.schedule_e_line == 19  # Other -> Line 19
            # The stored description is the trimmed, non-empty text.
            assert txn.description == description.strip()  # type: ignore[union-attr]
            # Persisted and retrievable.
            listed = service.list_for_property(PROPERTY_ID)
            assert [t.id for t in listed.value] == [txn.id]
        else:
            # Blank / whitespace-only / absent -> rejected on the Other rule.
            assert not result.is_ok, (
                f"expected failure for Other with description={description!r}"
            )
            assert result.error.kind == "validation"
            assert result.error.field == "description"
            assert result.error.message  # a human-readable message is present
            # Nothing was persisted on the rejected path.
            assert service.list_for_property(PROPERTY_ID).value == []


# Feature: logstead, Property 15: Other expenses require a description
@settings(deadline=None, max_examples=200)
@given(
    category_id=st.sampled_from(_NON_OTHER_CATEGORY_IDS),
    description=_blank_description,
)
def test_non_other_categories_treat_description_as_optional(
    category_id: str,
    description: str | None,
) -> None:
    """Non-Other create succeeds even with a blank/absent description.

    Validates: Requirement 7.4
    """
    data = TransactionInput(
        property_id=PROPERTY_ID,
        date=VALID_DATE,
        amount=VALID_AMOUNT,
        # A valid type for any category; the description rule is type-agnostic.
        type=VALID_TYPE,
        category_id=category_id,
        description=description,
    )

    with _moto_service() as service:
        result = service.create(data)

        # No non-Other category requires a description, so a blank/absent one is
        # accepted and normalized to None.
        assert result.is_ok, (
            f"expected success for {category_id!r} with "
            f"description={description!r}"
        )
        txn = result.value
        assert txn.id
        assert txn.category_id == category_id
        assert txn.description is None
        # Persisted and retrievable.
        listed = service.list_for_property(PROPERTY_ID)
        assert [t.id for t in listed.value] == [txn.id]
