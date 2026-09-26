"""Property-based test: property creation is independent of RentCast (Task 7.4).

Design Property 5 (Requirement 3.7): *for any* enrichment outcome (record found,
no match, or provider unavailable), submitting an otherwise-valid property
results in the property being created. RentCast is an optional enrichment, never
a gate -- so enrichment failures must never block or propagate into creation.

This test drives that invariant universally by drawing a RentCast outcome across
the four operational cases the design calls out and then asserting two things in
every branch:

1. ``AddressEnrichmentService.enrich`` returns an ``EnrichmentResult`` and NEVER
   raises, mapping the RentCast outcome to the correct status:

   * found       -> ``details`` present.
   * not_found   -> ``details`` is ``None`` (RentCast ``success(None)``).
   * unavailable -> ``details`` is ``None`` and the result is retry-able
     (``can_retry_later``), covering both a RentCast ``failure("unavailable")``
     (5xx/error) and a transport-level *timeout*. The timeout case uses the real
     :class:`RentCastAdapter` over a fetch that raises ``TimeoutError`` -- the
     adapter converts that into a ``failure("unavailable")`` so it never
     propagates through the enrichment port and never blocks creation.

2. ``PropertyService.create`` SUCCEEDS for valid input regardless of that
   enrichment outcome, and the property is persisted -- with no dependency on
   enrichment (the service never touches an enrichment adapter).

The four RentCast outcomes are supplied by stub ports implementing the
``get_property_record`` slice the enrichment service depends on:

* ``found``     -> ``Result.success(PropertyDetails(...))``
* ``not_found`` -> ``Result.success(None)``
* ``error``     -> ``Result.failure("unavailable", ...)``
* ``timeout``   -> the real :class:`RentCastAdapter` fronting a fetch that
  *raises* ``TimeoutError``. The adapter is the component that converts a
  transport timeout into a ``failure("unavailable")`` Result (its documented
  contract), so this proves a timeout never propagates through the enrichment
  port and never blocks creation.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(with the GSI1 index the service relies on), following the fixture pattern in
``test_property_service_smoke.py``. Per-example table provisioning is not
instantaneous, so the deadline is disabled; the example count is held at >= 100.

Validates: Requirements 3.7 (and related 3.4-3.6)
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.rentcast import RentCastAdapter
from logstead.models.property import PropertyDetails, PropertyInput
from logstead.models.result import Result
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.enrichment import AddressEnrichmentService, EnrichmentResult
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"


@contextlib.contextmanager
def _moto_table():
    """Provision an isolated moto single-table DynamoDB with GSI1.

    Yields a :class:`DynamoRepository` bound to a freshly created table so each
    Hypothesis example runs against a clean store.
    """
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
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
        yield DynamoRepository(ddb, TABLE_NAME)


# --- Stub RentCast ports, one per operational outcome --------------------------
#
# Each implements the ``get_property_record(address) -> Result[PropertyDetails |
# None]`` slice that AddressEnrichmentService depends on. No network is touched.


class _FoundPort:
    """RentCast returns a record -> success carrying PropertyDetails."""

    def __init__(self, details: PropertyDetails) -> None:
        self._details = details

    def get_property_record(self, address: str) -> Result[PropertyDetails | None]:
        return Result.success(self._details)


class _NotFoundPort:
    """RentCast has no record (404/empty) -> success carrying None."""

    def get_property_record(self, address: str) -> Result[PropertyDetails | None]:
        return Result.success(None)


class _ErrorPort:
    """RentCast failed / 5xx -> a typed 'unavailable' failure."""

    def get_property_record(self, address: str) -> Result[PropertyDetails | None]:
        return Result.failure(
            "unavailable", "Property enrichment provider returned an error."
        )


def _timeout_adapter() -> RentCastAdapter:
    """The REAL RentCast adapter over a fetch that raises ``TimeoutError``.

    Proves the adapter (the component responsible for it) converts a transport
    timeout into a ``failure("unavailable")`` Result, so a timeout never
    propagates through the enrichment port. No network is touched.
    """

    def _raising_fetch(url, headers, timeout):
        raise TimeoutError("RentCast request timed out")

    return RentCastAdapter(api_key="test-key", fetch=_raising_fetch)


# The four cases the task calls out: found / not_found / error / timeout.
_RENTCAST_CASES = ("found", "not_found", "error", "timeout")


def _make_rentcast_port(case: str, details: PropertyDetails):
    if case == "found":
        return _FoundPort(details)
    if case == "not_found":
        return _NotFoundPort()
    if case == "error":
        return _ErrorPort()
    if case == "timeout":
        return _timeout_adapter()
    raise AssertionError(f"unknown rentcast case: {case}")  # pragma: no cover


# --- Strategies ----------------------------------------------------------------

_non_blank = st.text(min_size=1, max_size=60).filter(lambda s: s.strip() != "")

# A sparse PropertyDetails for the "found" case; a couple of representative
# fields are enough to assert details-present mapping.
_details = st.builds(
    PropertyDetails,
    city=st.one_of(st.none(), _non_blank),
    state=st.one_of(st.none(), st.sampled_from(["CA", "NY", "TX", "WA"])),
    bedrooms=st.one_of(st.none(), st.integers(min_value=0, max_value=12)),
    bathrooms=st.one_of(st.none(), st.sampled_from([Decimal("1"), Decimal("2.5")])),
)


# Feature: logstead, Property 5: Property creation succeeds regardless of RentCast availability
@settings(deadline=None, max_examples=150)
@given(
    case=st.sampled_from(_RENTCAST_CASES),
    name=_non_blank,
    address=_non_blank,
    details=_details,
)
def test_property_creation_succeeds_regardless_of_rentcast_availability(
    case: str, name: str, address: str, details: PropertyDetails
) -> None:
    """Enrichment never raises/blocks; valid property is always created.

    Validates: Requirements 3.7 (and related 3.4-3.6)
    """
    rentcast = _make_rentcast_port(case, details)
    enrichment = AddressEnrichmentService(autocomplete=None, rentcast=rentcast)

    # 1) enrich() returns an EnrichmentResult and NEVER raises, with status
    #    mapping correctly for each outcome.
    result = enrichment.enrich(address)
    assert isinstance(result, EnrichmentResult)

    if case == "found":
        assert result.status == "found"
        assert result.is_found
        assert result.details is details  # the exact record is handed back
        assert not result.can_retry_later
    elif case == "not_found":
        assert result.status == "not_found"
        assert result.details is None
        assert not result.can_retry_later  # definitive: no retry
        assert result.message  # user-facing "no data found" message
    else:  # "error" or "timeout" -> unavailable (retry-able)
        assert result.status == "unavailable"
        assert result.details is None
        assert result.can_retry_later  # transient: retry allowed
        assert result.message

    # 2) PropertyService.create SUCCEEDS for valid input regardless of the
    #    enrichment outcome, and the property is persisted. Creation does not
    #    depend on enrichment -- the service never touches an enrichment adapter.
    with _moto_table() as repo:
        service = PropertyService(repo, UserContext(user_id="user-1"))
        created = service.create(PropertyInput(name=name, address_text=address))

        assert created.is_ok, f"creation must succeed for case={case!r}"
        prop = created.value
        assert prop.id
        assert prop.user_id == "user-1"
        assert prop.name == name.strip()
        assert prop.address_text == address.strip()

        # The property is persisted independently of the enrichment result.
        assert [p.id for p in service.list()] == [prop.id]
        assert service.get(prop.id).is_ok
