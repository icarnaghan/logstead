"""Property-based test for stored usage days (design Property 25).

Property 25 states that *for any* property and tax year with stored fair rental
days and personal use days, the report header reports those exact values. The
Schedule E report header reads its Fair_Rental_Days / Personal_Use_Days directly
from the stored :class:`PropertyUsageYear` (Requirements 2.8, 10.2), so the
property is exercised by round-tripping arbitrary non-negative day counts through
``set_usage_days`` -> ``get_usage_days`` and asserting the values are preserved
exactly -- these are precisely the values the report header will surface.

The test also asserts the negative-day guard: any negative fair-rental or
personal-use day count is rejected with a field-identifying validation error and
never stored (so the header can never read an invalid value).

Validates: Requirements 2.8, 10.2
"""

from __future__ import annotations

from contextlib import contextmanager

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"


@contextmanager
def _service():
    """Yield a PropertyService on a fresh moto single-table DynamoDB (with GSI1).

    Used as a context manager inside each Hypothesis example so every generated
    input runs against a clean table (function-scoped fixtures are not reset
    between ``@given`` inputs).
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        repo = DynamoRepository(client, TABLE_NAME)
        yield PropertyService(repo, UserContext(user_id="user-1"))


# Non-negative day counts a real header could display: a tax year cannot have
# more than 366 days, but generate a wider range so the round-trip is exercised
# beyond just calendar-valid values.
_days = st.integers(min_value=0, max_value=1000)

# Tax years span a realistic filing range.
_tax_years = st.integers(min_value=1900, max_value=3000)


# Feature: logstead, Property 25: Report header reflects stored usage days
@settings(deadline=None, max_examples=200)
@given(
    tax_year=_tax_years,
    fair_rental_days=_days,
    personal_use_days=_days,
)
def test_report_header_reflects_stored_usage_days(
    tax_year: int,
    fair_rental_days: int,
    personal_use_days: int,
) -> None:
    """Stored usage days round-trip exactly to what the report header reads.

    For any non-negative day counts and any tax year, after ``set_usage_days``
    the ``get_usage_days`` read (the source the Schedule E header reads from)
    returns the identical fair-rental days, personal-use days, and tax year.
    """
    with _service() as service:
        prop = service.create(
            PropertyInput(name="P", address_text="A")
        ).value

        stored = service.set_usage_days(
            prop.id,
            tax_year,
            fair_rental_days=fair_rental_days,
            personal_use_days=personal_use_days,
        )
        assert stored.is_ok
        # The value returned from the write already reflects what was stored.
        assert stored.value.fair_rental_days == fair_rental_days
        assert stored.value.personal_use_days == personal_use_days
        assert stored.value.tax_year == tax_year

        # The header reads via get_usage_days: it must see the exact stored values.
        read = service.get_usage_days(prop.id, tax_year)
        assert read.is_ok
        assert read.value.fair_rental_days == fair_rental_days
        assert read.value.personal_use_days == personal_use_days
        assert read.value.tax_year == tax_year
        assert read.value.property_id == prop.id


# Feature: logstead, Property 25: Report header reflects stored usage days
@settings(deadline=None, max_examples=200)
@given(
    tax_year=_tax_years,
    negative=st.integers(max_value=-1),
    valid=_days,
    negative_field=st.sampled_from(["fair_rental_days", "personal_use_days"]),
)
def test_negative_usage_days_are_rejected(
    tax_year: int,
    negative: int,
    valid: int,
    negative_field: str,
) -> None:
    """Negative day counts are rejected with a field-identifying validation error.

    An invalid day count is never stored, so the report header can never read a
    negative value for either field.
    """
    with _service() as service:
        prop = service.create(
            PropertyInput(name="P", address_text="A")
        ).value

        if negative_field == "fair_rental_days":
            fair_rental_days, personal_use_days = negative, valid
        else:
            fair_rental_days, personal_use_days = valid, negative

        result = service.set_usage_days(
            prop.id,
            tax_year,
            fair_rental_days=fair_rental_days,
            personal_use_days=personal_use_days,
        )
        assert not result.is_ok
        assert result.error.kind == "validation"
        assert result.error.field == negative_field

        # Nothing was stored: the header would find no usage row for this year.
        read = service.get_usage_days(prop.id, tax_year)
        assert not read.is_ok
        assert read.error.kind == "not_found"
