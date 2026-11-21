"""Unit tests for the Textract adapter (Requirement 2.1).

Exercises the two async document-analysis calls against a **hand fake** Textract
client that records how it was called and returns canned response dicts. A hand
fake is preferred over ``moto`` here for determinism (and because Textract async
analysis support in moto is limited). Live Amazon Textract is never called.
"""

from __future__ import annotations

from logstead.adapters.textract import TextractAdapter, TextractResult


class FakeTextractClient:
    """Records calls and returns canned responses for the two adapter methods.

    ``start_document_analysis`` records its kwargs and returns a fixed ``JobId``.
    ``get_document_analysis`` serves a queued list of response pages in order,
    recording the kwargs of every call (so ``NextToken`` threading is testable).
    """

    def __init__(self, *, job_id="job-123", get_pages=None):
        self._job_id = job_id
        self._get_pages = list(get_pages or [])
        self.start_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def start_document_analysis(self, **kwargs):
        self.start_calls.append(kwargs)
        return {"JobId": self._job_id}

    def get_document_analysis(self, **kwargs):
        self.get_calls.append(kwargs)
        if not self._get_pages:
            raise AssertionError("get_document_analysis called more times than queued")
        return self._get_pages.pop(0)


# --- start_document_analysis ------------------------------------------------


def test_start_passes_forms_and_tables_and_s3_location_and_returns_job_id():
    client = FakeTextractClient(job_id="7b1f-abc")
    adapter = TextractAdapter(client)

    job_id = adapter.start_document_analysis("logstead-files", "imports/schedule-e/u/j.pdf")

    assert job_id == "7b1f-abc"
    assert len(client.start_calls) == 1
    call = client.start_calls[0]
    # FeatureTypes must be exactly FORMS + TABLES.
    assert call["FeatureTypes"] == ["FORMS", "TABLES"]
    # The S3 location must point at the uploaded object (Name == key).
    assert call["DocumentLocation"] == {
        "S3Object": {"Bucket": "logstead-files", "Name": "imports/schedule-e/u/j.pdf"}
    }


# --- get_document_analysis --------------------------------------------------


def test_get_drains_next_token_across_three_pages_into_one_blocks_list():
    pages = [
        {
            "JobStatus": "SUCCEEDED",
            "Blocks": [{"Id": "b1"}, {"Id": "b2"}],
            "StatusMessage": "all good",
            "NextToken": "tok-1",
        },
        {
            "JobStatus": "SUCCEEDED",
            "Blocks": [{"Id": "b3"}],
            "NextToken": "tok-2",
        },
        {
            "JobStatus": "SUCCEEDED",
            "Blocks": [{"Id": "b4"}, {"Id": "b5"}],
            # No NextToken -> last page.
        },
    ]
    client = FakeTextractClient(get_pages=pages)
    adapter = TextractAdapter(client)

    result = adapter.get_document_analysis("job-xyz")

    assert isinstance(result, TextractResult)
    assert result.status == "SUCCEEDED"
    # All five blocks aggregated across the three pages, in order.
    assert [b["Id"] for b in result.blocks] == ["b1", "b2", "b3", "b4", "b5"]
    # StatusMessage surfaced from the first page that carried one.
    assert result.status_message == "all good"

    # Three GetDocumentAnalysis calls were made, threading the NextToken.
    assert len(client.get_calls) == 3
    assert client.get_calls[0] == {"JobId": "job-xyz"}
    assert client.get_calls[1] == {"JobId": "job-xyz", "NextToken": "tok-1"}
    assert client.get_calls[2] == {"JobId": "job-xyz", "NextToken": "tok-2"}


def test_get_single_page_in_progress_has_no_message_and_empty_blocks():
    client = FakeTextractClient(get_pages=[{"JobStatus": "IN_PROGRESS"}])
    adapter = TextractAdapter(client)

    result = adapter.get_document_analysis("job-1")

    assert result.status == "IN_PROGRESS"
    assert result.blocks == []
    assert result.status_message is None
    assert len(client.get_calls) == 1


def test_get_surfaces_failed_status_and_message():
    pages = [{"JobStatus": "FAILED", "StatusMessage": "document unreadable", "Blocks": []}]
    client = FakeTextractClient(get_pages=pages)
    adapter = TextractAdapter(client)

    result = adapter.get_document_analysis("job-2")

    assert result.status == "FAILED"
    assert result.status_message == "document unreadable"
    assert result.blocks == []


def test_get_falls_back_to_warnings_for_message():
    pages = [
        {
            "JobStatus": "PARTIAL_SUCCESS",
            "Blocks": [{"Id": "b1"}],
            "Warnings": [{"ErrorCode": "PAGE_LIMIT_EXCEEDED", "Pages": [12]}],
        }
    ]
    client = FakeTextractClient(get_pages=pages)
    adapter = TextractAdapter(client)

    result = adapter.get_document_analysis("job-3")

    assert result.status == "PARTIAL_SUCCESS"
    assert result.status_message == "PAGE_LIMIT_EXCEEDED"
    assert [b["Id"] for b in result.blocks] == ["b1"]
