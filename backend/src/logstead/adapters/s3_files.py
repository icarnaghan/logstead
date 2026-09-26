"""S3 file adapter for object storage over one bucket with prefixed keys
(Requirements 4.1, 5.8).

Logstead keeps a single S3 bucket for every kind of file it stores — property
photos, transaction receipts, uploaded expense-summary PDFs, and exported
Schedule E reports — and distinguishes them by **key prefix**. DynamoDB stores
only metadata plus the S3 key; the bytes live in S3 and the browser talks to S3
directly through **pre-signed URLs** so file payloads never pass through the
Lambda (see design "File storage" and the Persistence layer notes).

This adapter owns three responsibilities and nothing else:

* Issue a pre-signed **PUT** URL so the browser can upload an object directly.
* Issue a pre-signed **GET** URL so the browser can download an object directly.
* **Delete** an object.

Higher-level policy (content-type allow-lists, writing the DynamoDB metadata
item only after a confirmed upload) lives in the Photo/Transaction services, not
here. Keeping the adapter thin makes it trivial to exercise against ``moto``.

The boto3 S3 client and bucket name are injected via the constructor so tests
can back the adapter with ``moto`` and no live AWS calls are ever made.
"""

from __future__ import annotations

from typing import Any

# --- Key prefixes -----------------------------------------------------------
#
# Every object in the shared bucket is filed under one of these top-level
# prefixes so the four file categories never collide and are easy to scope,
# lifecycle, or audit independently.
PHOTO_PREFIX = "photos"
RECEIPT_PREFIX = "receipts"
IMPORT_PREFIX = "imports"
EXPORT_PREFIX = "exports"

# Default lifetime for an issued pre-signed URL (seconds). One hour is long
# enough for an interactive browser upload/download yet short enough to bound
# exposure of the signed link.
DEFAULT_EXPIRY_SECONDS = 3600


def _clean_segment(segment: str) -> str:
    """Normalize a single key path segment.

    Strips surrounding whitespace and any leading/trailing slashes so callers
    can pass values like ``"/photos/"`` or ``" abc "`` without producing empty
    or double-slashed segments in the final key.
    """
    return str(segment).strip().strip("/")


def build_key(*segments: str) -> str:
    """Join ``segments`` into a single slash-delimited S3 object key.

    Empty or slash-only segments are dropped, and each segment is trimmed, so
    ``build_key("photos", propertyId, filename)`` yields a clean
    ``photos/<propertyId>/<filename>`` key. Raises ``ValueError`` if nothing
    usable remains (an empty key is never a valid object key).
    """
    parts = [cleaned for segment in segments if (cleaned := _clean_segment(segment))]
    if not parts:
        raise ValueError("Cannot build an S3 key from empty segments")
    return "/".join(parts)


def photo_key(property_id: str, filename: str) -> str:
    """Build a key for a property photo: ``photos/<propertyId>/<filename>``."""
    return build_key(PHOTO_PREFIX, property_id, filename)


def receipt_key(transaction_id: str, filename: str) -> str:
    """Build a key for a transaction receipt: ``receipts/<txnId>/<filename>``."""
    return build_key(RECEIPT_PREFIX, transaction_id, filename)


def import_key(*segments: str) -> str:
    """Build a key for an uploaded expense-summary PDF under ``imports/``."""
    return build_key(IMPORT_PREFIX, *segments)


def export_key(*segments: str) -> str:
    """Build a key for an exported report file under ``exports/``."""
    return build_key(EXPORT_PREFIX, *segments)


class S3FileAdapter:
    """Thin wrapper over a single S3 bucket for pre-signed URL issuance + delete.

    Args:
        s3_client: A boto3 S3 client (``boto3.client("s3")``). Injected so tests
            can supply a ``moto``-backed client and never hit live AWS.
        bucket: The name of the single bucket that stores all Logstead files.
    """

    def __init__(self, s3_client: Any, bucket: str) -> None:
        if not bucket:
            raise ValueError("bucket must be a non-empty string")
        self._s3 = s3_client
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        """The bucket this adapter operates on."""
        return self._bucket

    def presigned_put_url(
        self,
        key: str,
        content_type: str,
        *,
        expires_in: int = DEFAULT_EXPIRY_SECONDS,
    ) -> str:
        """Issue a pre-signed URL the browser can PUT an object to.

        The ``content_type`` is bound into the signature so the eventual upload
        must declare the same type it was authorized for. Callers that need to
        assemble a key from components should use :func:`build_key` (or one of
        the ``*_key`` helpers) first.

        Args:
            key: The full object key (already prefixed).
            content_type: The MIME type the client will upload with.
            expires_in: URL lifetime in seconds.

        Returns:
            A pre-signed HTTPS URL for a PUT upload.
        """
        return self._s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )

    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: int = DEFAULT_EXPIRY_SECONDS,
    ) -> str:
        """Issue a pre-signed URL the browser can GET (download) an object from.

        Args:
            key: The full object key.
            expires_in: URL lifetime in seconds.

        Returns:
            A pre-signed HTTPS URL for a GET download.
        """
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        """Write ``body`` to the bucket at ``key`` with the given content type.

        Used for server-generated files (e.g. exported Schedule E reports)
        where the bytes are produced in the Lambda rather than uploaded by the
        browser. Photos/receipts/PDFs still arrive via pre-signed PUT URLs;
        this is only for objects the backend materializes itself.

        Args:
            key: The full object key (already prefixed).
            body: The raw object bytes to store.
            content_type: The MIME type to record on the object.
        """
        self._s3.put_object(
            Bucket=self._bucket, Key=key, Body=body, ContentType=content_type
        )

    def delete_object(self, key: str) -> None:
        """Delete the object at ``key`` from the bucket.

        S3 delete is idempotent — deleting a missing key is not an error — which
        matches the service-layer contract where a metadata item and its object
        are removed together.
        """
        self._s3.delete_object(Bucket=self._bucket, Key=key)
