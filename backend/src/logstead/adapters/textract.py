"""Textract adapter for asynchronous document analysis (Requirement 2.1).

Schedule E PDF extraction ("layer 2") reads a prior-year tax-return PDF with
Amazon Textract's **asynchronous** document-analysis API:
``StartDocumentAnalysis`` returns a ``JobId`` immediately while the OCR runs
server-side at AWS, and ``GetDocumentAnalysis(JobId)`` retrieves the result
later (paginated with a ``NextToken``).

This adapter is a thin wrapper over the boto3 ``textract`` client, mirroring
``S3FileAdapter``'s shape: the client is **injected** via the constructor so
tests back it with a hand fake (or ``moto``, if it supports Textract) and never
hit live AWS.

It owns exactly two responsibilities and no policy:

* ``start_document_analysis`` — issue ``StartDocumentAnalysis`` against an S3
  object with ``FeatureTypes=['FORMS','TABLES']`` and return the ``JobId``.
* ``get_document_analysis`` — issue ``GetDocumentAnalysis(JobId)``, draining
  every ``NextToken`` page into one aggregated blocks list, and return a small
  :class:`TextractResult` value object (status + blocks + optional message).

All "what does the result mean" logic — locating Schedule E, reading columns
and amounts, confidence thresholds — lives in the service and the pure parser,
not here. Keeping the adapter thin makes it trivial to exercise against a fake.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["TextractResult", "TextractAdapter"]

# The two Textract table/form features the parser depends on: FORMS gives the
# key/value pairs (addresses, tax year) and TABLES gives the Schedule E Part I
# property-column grid of line amounts.
_FEATURE_TYPES = ["FORMS", "TABLES"]


@dataclass
class TextractResult:
    """The aggregated outcome of a ``GetDocumentAnalysis`` call.

    Attributes:
        status: The Textract ``JobStatus`` — one of ``IN_PROGRESS``,
            ``SUCCEEDED``, ``FAILED``, or ``PARTIAL_SUCCESS``.
        blocks: The ``Block`` dicts aggregated across every ``NextToken`` page.
        status_message: A human-readable message when Textract surfaces one
            (``StatusMessage`` or a joined ``Warnings`` summary); ``None`` when
            the job carries no message.
    """

    status: str
    blocks: list[dict] = field(default_factory=list)
    status_message: str | None = None


class TextractAdapter:
    """Thin wrapper over the boto3 ``textract`` client for async analysis.

    Args:
        textract_client: A boto3 Textract client (``boto3.client("textract")``).
            Injected so tests can supply a fake/``moto`` client and never hit
            live AWS.
    """

    def __init__(self, textract_client: Any) -> None:
        self._textract = textract_client

    def start_document_analysis(self, bucket: str, key: str) -> str:
        """Start async document analysis over an S3 object; return the ``JobId``.

        Issues ``StartDocumentAnalysis`` with ``FeatureTypes=['FORMS','TABLES']``
        against the object at ``s3://<bucket>/<key>``. The long OCR work runs
        server-side at AWS between this call and the later
        :meth:`get_document_analysis`; this call itself is a fast control-plane
        request that returns the job identifier to poll on.

        Args:
            bucket: The S3 bucket holding the uploaded PDF.
            key: The S3 object key of the uploaded PDF.

        Returns:
            The Textract ``JobId`` to poll with :meth:`get_document_analysis`.
        """
        response = self._textract.start_document_analysis(
            DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
            FeatureTypes=_FEATURE_TYPES,
        )
        return response["JobId"]

    def get_document_analysis(self, job_id: str) -> TextractResult:
        """Fetch analysis results for ``job_id``, draining all ``NextToken`` pages.

        Calls ``GetDocumentAnalysis(JobId=job_id)`` and loops while the response
        carries a ``NextToken``, passing the token back on each subsequent call,
        so every page's ``Blocks`` are concatenated into one aggregated list.
        The job status is read from the first page's ``JobStatus`` (it is stable
        across pages); any ``StatusMessage``/``Warnings`` are surfaced on the
        returned value object.

        Args:
            job_id: The Textract ``JobId`` returned by
                :meth:`start_document_analysis`.

        Returns:
            A :class:`TextractResult` with the job status, the aggregated
            blocks list, and any status message.
        """
        blocks: list[dict] = []
        status: str = ""
        status_message: str | None = None
        next_token: str | None = None

        while True:
            params: dict[str, Any] = {"JobId": job_id}
            if next_token is not None:
                params["NextToken"] = next_token
            response = self._textract.get_document_analysis(**params)

            # JobStatus is stable across pages; keep the latest reported value.
            status = response.get("JobStatus", status)

            page_message = self._extract_status_message(response)
            if page_message and status_message is None:
                status_message = page_message

            blocks.extend(response.get("Blocks", []) or [])

            next_token = response.get("NextToken")
            if not next_token:
                break

        return TextractResult(
            status=status, blocks=blocks, status_message=status_message
        )

    @staticmethod
    def _extract_status_message(response: dict) -> str | None:
        """Pull a human-readable message from a ``GetDocumentAnalysis`` page.

        Prefers the explicit ``StatusMessage``; otherwise joins any
        ``Warnings`` error messages into a single string. Returns ``None`` when
        the page carries neither.
        """
        message = response.get("StatusMessage")
        if message:
            return str(message)

        warnings = response.get("Warnings")
        if warnings:
            texts = [
                str(w.get("ErrorCode"))
                for w in warnings
                if isinstance(w, dict) and w.get("ErrorCode")
            ]
            if texts:
                return "; ".join(texts)
        return None
