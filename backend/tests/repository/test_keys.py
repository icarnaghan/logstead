"""Unit tests for logstead.repository.keys (Requirements 5.4, 5.5).

These example/edge-case unit tests verify that:

* key construction matches the documented single-table conventions;
* inverted-date encoding round-trips (``date_from_inverted(inverted_date(d)) == d``);
* a newer transaction date produces a sort key that sorts *before* an older
  one under plain string comparison, so an ascending DynamoDB scan yields
  newest-first (Requirement 5.4), including on the tax-year GSI2 (Requirement 5.5).
"""

from __future__ import annotations

from datetime import date

import pytest

from logstead.repository import keys


# --- Inverted-date encoding --------------------------------------------------

class TestInvertedDate:
    def test_to_yyyymmdd(self) -> None:
        assert keys.to_yyyymmdd(date(2024, 3, 7)) == 20240307

    def test_from_yyyymmdd(self) -> None:
        assert keys.from_yyyymmdd(20240307) == date(2024, 3, 7)

    def test_yyyymmdd_round_trip(self) -> None:
        d = date(2023, 11, 30)
        assert keys.from_yyyymmdd(keys.to_yyyymmdd(d)) == d

    def test_inverted_date_is_zero_padded_eight_digit_token(self) -> None:
        # 99999999 - 20240307 = 79759692
        token = keys.inverted_date(date(2024, 3, 7))
        assert token == "79759692"
        assert len(token) == 8

    def test_inverted_date_pads_to_width_for_far_future_dates(self) -> None:
        # A date near the 9999-12-31 ceiling yields a small inverted value that
        # must be zero-padded to eight chars so string order == numeric order.
        # 99999999 - 99991230 = 8769.
        token = keys.inverted_date(date(9999, 12, 30))
        assert token == "00008769"
        assert len(token) == 8

    def test_inverted_date_round_trip(self) -> None:
        d = date(2024, 3, 7)
        assert keys.date_from_inverted(keys.inverted_date(d)) == d

    @pytest.mark.parametrize(
        "d",
        [
            date(1970, 1, 1),
            date(2000, 2, 29),  # leap day
            date(2024, 1, 1),
            date(2024, 12, 31),
            date(9999, 12, 31),
        ],
    )
    def test_inverted_date_round_trip_across_range(self, d: date) -> None:
        assert keys.date_from_inverted(keys.inverted_date(d)) == d

    def test_date_from_inverted_accepts_int_token(self) -> None:
        d = date(2022, 6, 15)
        as_int = int(keys.inverted_date(d))
        assert keys.date_from_inverted(as_int) == d

    def test_newer_date_yields_lexicographically_smaller_token(self) -> None:
        newer = keys.inverted_date(date(2024, 12, 31))
        older = keys.inverted_date(date(2024, 1, 1))
        # Newer sorts first under plain string comparison (newest-first on scan).
        assert newer < older

    def test_string_order_matches_reverse_chronological_order(self) -> None:
        dates = [
            date(2020, 1, 1),
            date(2022, 7, 4),
            date(2024, 3, 7),
            date(2024, 3, 8),
            date(2025, 12, 31),
        ]
        tokens = [keys.inverted_date(d) for d in dates]
        # Sorting the tokens ascending (as DynamoDB does) must reproduce the
        # dates in strictly descending chronological order.
        by_token = [d for _, d in sorted(zip(tokens, dates))]
        assert by_token == sorted(dates, reverse=True)


# --- User keys ---------------------------------------------------------------

class TestUserKeys:
    def test_user_pk(self) -> None:
        assert keys.user_pk("u1") == "USER#u1"

    def test_user_profile_sk(self) -> None:
        assert keys.user_profile_sk() == "PROFILE"


# --- Property keys -----------------------------------------------------------

class TestPropertyKeys:
    def test_property_scoped_pk(self) -> None:
        assert keys.property_scoped_pk("p1") == "PROPERTY#p1"

    def test_property_meta_sk(self) -> None:
        assert keys.property_meta_sk() == "META"

    def test_property_user_sk(self) -> None:
        assert keys.property_user_sk("p1") == "PROP#p1"

    def test_property_list_prefix(self) -> None:
        assert keys.property_list_prefix() == "PROP#"
        assert keys.property_user_sk("p1").startswith(keys.property_list_prefix())

    def test_property_details_sk(self) -> None:
        assert keys.property_details_sk() == "DETAILS"


# --- Usage / photo keys ------------------------------------------------------

class TestUsageAndPhotoKeys:
    def test_usage_sk(self) -> None:
        assert keys.usage_sk(2024) == "USAGE#2024"

    def test_photo_sk(self) -> None:
        assert keys.photo_sk("ph1") == "PHOTO#ph1"

    def test_photo_list_prefix(self) -> None:
        assert keys.photo_list_prefix() == "PHOTO#"
        assert keys.photo_sk("ph1").startswith(keys.photo_list_prefix())


# --- Category keys -----------------------------------------------------------

class TestCategoryKeys:
    def test_category_pk(self) -> None:
        assert keys.category_pk("rents") == "CATEGORY#rents"

    def test_category_sk(self) -> None:
        assert keys.category_sk() == "META"


# --- Transaction / document keys ---------------------------------------------

class TestTransactionKeys:
    def test_transaction_sk_construction(self) -> None:
        d = date(2024, 3, 7)
        sk = keys.transaction_sk(d, "t1")
        assert sk == f"TXN#{keys.inverted_date(d)}#t1"
        assert sk == "TXN#79759692#t1"

    def test_transaction_list_prefix(self) -> None:
        assert keys.transaction_list_prefix() == "TXN#"
        assert keys.transaction_sk(date(2024, 3, 7), "t1").startswith(
            keys.transaction_list_prefix()
        )

    def test_newer_transaction_sorts_before_older(self) -> None:
        # Requirement 5.4: same property, different dates -> newest-first on an
        # ascending sort-key scan.
        newer = keys.transaction_sk(date(2024, 6, 1), "tA")
        older = keys.transaction_sk(date(2024, 1, 1), "tB")
        assert newer < older

    def test_transactions_sort_newest_first(self) -> None:
        sks = [
            keys.transaction_sk(date(2023, 1, 15), "a"),
            keys.transaction_sk(date(2024, 9, 30), "b"),
            keys.transaction_sk(date(2024, 9, 29), "c"),
            keys.transaction_sk(date(2022, 12, 31), "d"),
        ]
        ascending = sorted(sks)  # what DynamoDB returns
        recovered_dates = [
            keys.date_from_inverted(sk.split("#")[1]) for sk in ascending
        ]
        assert recovered_dates == sorted(recovered_dates, reverse=True)

    def test_document_sk_is_nested_under_transaction(self) -> None:
        d = date(2024, 3, 7)
        doc_sk = keys.document_sk(d, "t1", "doc9")
        assert doc_sk == f"{keys.transaction_sk(d, 't1')}#DOC#doc9"
        assert doc_sk.startswith(keys.transaction_sk(d, "t1"))


# --- Asset / schedule keys ---------------------------------------------------

class TestAssetAndScheduleKeys:
    def test_asset_sk(self) -> None:
        assert keys.asset_sk("a1") == "ASSET#a1"

    def test_asset_list_prefix(self) -> None:
        assert keys.asset_list_prefix() == "ASSET#"
        assert keys.asset_sk("a1").startswith(keys.asset_list_prefix())

    def test_schedule_row_sk(self) -> None:
        assert keys.schedule_row_sk("a1", 2024) == "ASSET#a1#SCHED#2024"

    def test_schedule_list_prefix(self) -> None:
        prefix = keys.schedule_list_prefix("a1")
        assert prefix == "ASSET#a1#SCHED#"
        assert keys.schedule_row_sk("a1", 2024).startswith(prefix)

    def test_schedule_row_is_distinguishable_from_asset_row(self) -> None:
        # An asset row must not be picked up by the schedule-row prefix, and a
        # schedule row starts with the asset prefix (co-located).
        asset = keys.asset_sk("a1")
        row = keys.schedule_row_sk("a1", 2024)
        assert row.startswith(keys.asset_list_prefix())
        assert not asset.startswith(keys.schedule_list_prefix("a1"))


# --- Import / draft keys -----------------------------------------------------

class TestImportAndDraftKeys:
    def test_import_pk(self) -> None:
        assert keys.import_pk("imp1") == "IMPORT#imp1"

    def test_import_meta_sk(self) -> None:
        assert keys.import_meta_sk() == "META"

    def test_draft_sk(self) -> None:
        assert keys.draft_sk("d1") == "DRAFT#d1"

    def test_draft_list_prefix(self) -> None:
        assert keys.draft_list_prefix() == "DRAFT#"
        assert keys.draft_sk("d1").startswith(keys.draft_list_prefix())


# --- GSI1 keys ---------------------------------------------------------------

class TestGsi1Keys:
    def test_gsi1_property_keys(self) -> None:
        pk, sk = keys.gsi1_property_keys("u1", "p1")
        assert pk == "USER#u1"
        assert sk == "PROP#p1"

    def test_gsi1_import_keys(self) -> None:
        pk, sk = keys.gsi1_import_keys("p1", "imp1")
        assert pk == "PROPERTY#p1"
        assert sk == "IMPORT#imp1"


# --- GSI2 keys (tax-year-scoped access) --------------------------------------

class TestGsi2Keys:
    def test_gsi2_year_pk(self) -> None:
        assert keys.gsi2_year_pk("p1", 2024) == "PROPERTY#p1#YEAR#2024"

    def test_gsi2_transaction_sk_construction(self) -> None:
        d = date(2024, 3, 7)
        assert keys.gsi2_transaction_sk(d, "t1") == f"TXN#{keys.inverted_date(d)}#t1"

    def test_gsi2_transaction_prefix(self) -> None:
        assert keys.gsi2_transaction_prefix() == "TXN#"
        assert keys.gsi2_transaction_sk(date(2024, 3, 7), "t1").startswith(
            keys.gsi2_transaction_prefix()
        )

    def test_gsi2_transactions_within_year_sort_newest_first(self) -> None:
        # Requirement 5.5: tax-year-scoped results are also date-descending.
        newer = keys.gsi2_transaction_sk(date(2024, 12, 1), "tA")
        older = keys.gsi2_transaction_sk(date(2024, 2, 1), "tB")
        assert newer < older

    def test_gsi2_schedule_sk(self) -> None:
        assert keys.gsi2_schedule_sk("a1") == "SCHED#a1"

    def test_gsi2_schedule_prefix(self) -> None:
        assert keys.gsi2_schedule_prefix() == "SCHED#"
        assert keys.gsi2_schedule_sk("a1").startswith(keys.gsi2_schedule_prefix())
