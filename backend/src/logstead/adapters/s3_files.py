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

import re
from typing import IO, Any

# --- Key prefixes -----------------------------------------------------------
#
# Every object in the shared bucket is filed under one of these top-level
# prefixes so the four file categories never collide and are easy to scope,
# lifecycle, or audit independently.
PHOTO_PREFIX = "photos"
RECEIPT_PREFIX = "receipts"
IMPORT_PREFIX = "imports"
EXPORT_PREFIX = "exports"
BUSINESS_DOC_PREFIX = "business-docs"

# Default lifetime for an issued pre-signed URL (seconds). One hour is long
# enough for an interactive browser upload/download yet short enough to bound
# exposure of the signed link.
DEFAULT_EXPIRY_SECONDS = 3600

# Lifetime for an issued pre-signed **upload** (PUT) URL. Ten minutes is ample
# for a browser upload and keeps a leaked URL useful only briefly.
UPLOAD_EXPIRY_SECONDS = 600

# --- Upload policy (S8) -----------------------------------------------------
#
# Content-type allow-lists per file kind. Kept in sync with the frontend
# ``accept`` attributes / allow-lists.
IMAGE_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)
IMAGE_OR_PDF_CONTENT_TYPES: frozenset[str] = IMAGE_CONTENT_TYPES | {
    "application/pdf"
}
# Receipts accept images and PDF (same set as business documents).
RECEIPT_CONTENT_TYPES = IMAGE_OR_PDF_CONTENT_TYPES

# Maximum object sizes. A presigned PUT cannot enforce a size, so these are
# enforced after the fact (see ``purge_if_oversized`` and the extraction
# confirm step).
MAX_IMAGE_BYTES = 25 * 1024 * 1024  # phone HEIC/JPEG photos
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024  # receipts / business documents
MAX_IMPORT_PDF_BYTES = 20 * 1024 * 1024  # Schedule E extraction PDFs

_MAX_FILENAME_LENGTH = 100
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\- ()]", re.UNICODE)


def sanitize_filename(filename: str | None, *, max_length: int = _MAX_FILENAME_LENGTH) -> str:
    """Return a safe display/key filename.

    Drops any directory part (``/`` or ``\\``), control characters and other
    characters outside word characters, ``.``, ``-``, space and parentheses
    (replaced by ``_``), strips leading dots/spaces (no hidden or ``..`` names),
    and caps the length while preserving a short extension. Falls back to
    ``"file"`` when nothing usable remains.
    """
    name = str(filename or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable())
    name = _UNSAFE_FILENAME_CHARS.sub("_", name).strip(" .")
    if len(name) > max_length:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = stem[: max_length - len(ext) - 1] + "." + ext
        else:
            name = name[:max_length]
        name = name.strip(" .")
    return name or "file"


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


def business_doc_key(business_id: str, filename: str) -> str:
    """Build a key for a business document: ``business-docs/<businessId>/<filename>``."""
    return build_key(BUSINESS_DOC_PREFIX, business_id, filename)


def import_key(*segments: str) -> str:
    """Build a key for an uploaded expense-summary PDF under ``imports/``."""
    return build_key(IMPORT_PREFIX, *segments)


def export_key(*segments: str) -> str:
    """Build a key for an exported report file under ``exports/``."""
    return build_key(EXPORT_PREFIX, *segments)


def combined_export_key(user_id: str, tax_year: int, filename: str) -> str:
    """exports/combined/<user_id>/<tax_year>/<filename>"""
    return export_key("combined", user_id, str(tax_year), filename)


def package_key(user_id: str, job_id: str, year: int) -> str:
    """Key for an accountant package ZIP under ``exports/packages/``."""
    return export_key(
        "packages", user_id, job_id, f"logstead-accountant-package-{int(year)}.zip"
    )


def pdf_key(user_id: str, random_id: str, filename: str) -> str:
    """Key for a generated report PDF under ``exports/pdf/``."""
    return export_key("pdf", user_id, random_id, filename)


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
        expires_in: int = UPLOAD_EXPIRY_SECONDS,
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
        download_filename: str | None = None,
    ) -> str:
        """Issue a pre-signed URL the browser can GET (download) an object from.

        Args:
            key: The full object key.
            expires_in: URL lifetime in seconds.
            download_filename: When given, the sanitized name is sent as a
                quoted ``attachment`` Content-Disposition.

        Returns:
            A pre-signed HTTPS URL for a GET download.
        """
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if download_filename is not None:
            safe = sanitize_filename(download_filename)
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        return self._s3.generate_presigned_url(
            "get_object",
            Params=params,
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

    def open_stream(self, key: str) -> tuple[IO[bytes], int] | None:
        """Return ``(body stream, content length)`` or ``None`` when absent."""
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=key)
        except Exception:  # noqa: BLE001 - missing key / any client error
            return None
        return resp["Body"], int(resp.get("ContentLength", 0))

    def upload_file(self, path: str, key: str, content_type: str) -> None:
        """Upload a local file with boto3's managed (multipart) transfer."""
        self._s3.upload_file(
            path, self._bucket, key, ExtraArgs={"ContentType": content_type}
        )

    def object_size(self, key: str) -> int | None:
        """Return the object's size in bytes, or ``None`` if it is absent."""
        try:
            head = self._s3.head_object(Bucket=self._bucket, Key=key)
        except Exception:  # noqa: BLE001 - missing key / any client error
            return None
        return int(head.get("ContentLength", 0))

    def purge_if_oversized(self, key: str, max_bytes: int) -> bool:
        """Delete the object when larger than ``max_bytes``; True if deleted.

        Presigned PUT URLs cannot enforce a size limit, so callers run this on
        the confirm/list step. An absent object is left alone (returns False).
        """
        size = self.object_size(key)
        if size is not None and size > max_bytes:
            self.delete_object(key)
            return True
        return False

    def delete_object(self, key: str) -> None:
        """Delete the object at ``key`` from the bucket.

        S3 delete is idempotent — deleting a missing key is not an error — which
        matches the service-layer contract where a metadata item and its object
        are removed together.
        """
        self._s3.delete_object(Bucket=self._bucket, Key=key)
