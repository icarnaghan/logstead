"""Photo Service: property photo upload, listing, and deletion (Requirement 4).

Property photos exist because RentCast Property Records do not include images
(Requirement 4 intro): the owner uploads their own visual records and associates
them with a property. The binary bytes live in Amazon S3; DynamoDB stores only a
:class:`~logstead.models.property.PropertyPhoto` metadata item (its S3 key,
content type, original filename, and upload timestamp). The browser uploads and
downloads directly against S3 through **pre-signed URLs**, so file payloads never
flow through the Lambda (design "File storage" / Photo Component).

This service composes two collaborators, both injected so tests can back them
with ``moto`` and no live AWS call is ever made:

* :class:`~logstead.adapters.s3_files.S3FileAdapter` — issues pre-signed PUT/GET
  URLs and deletes objects over the single shared bucket.
* :class:`~logstead.repository.dynamo_repo.DynamoRepository` — persists, lists,
  and deletes the ``PropertyPhoto`` metadata items under the property partition.

Responsibilities (design "Photo Component", Requirement 4)
----------------------------------------------------------
* :meth:`request_upload` — validate the declared content type against the image
  allow-list *before* issuing a URL (Requirement 4.2), build the photo S3 key,
  issue a pre-signed **PUT** URL, and record the ``PropertyPhoto`` metadata item
  so the uploaded object is tracked (Requirement 4.1).
* :meth:`list_photos` — return every photo associated with a property, each with
  a pre-signed **GET** URL for display (Requirements 4.3).
* :meth:`delete_photo` — remove **both** the S3 object and the DynamoDB metadata
  item, dissociating the photo from the property (Requirement 4.4);
  ``not_found`` when the photo does not exist.

Metadata-write timing
---------------------
The design's ``PhotoService`` protocol sketches a two-step ``request_upload`` +
``confirm_upload`` flow. This implementation keeps it simple and writes the
``PropertyPhoto`` metadata item **at request time**, in the same call that issues
the pre-signed PUT URL, so a photo is tracked as soon as its upload is
authorized. The content type is bound into the pre-signed URL, so the browser
can only upload the allowed type it was authorized for. (A future
``confirm_upload`` step could defer the metadata write until S3 confirms the
object exists; the storage shape is identical either way.)

Content-type allow-list (Requirement 4.2)
-----------------------------------------
Only the image MIME types in :data:`ALLOWED_CONTENT_TYPES` are accepted; anything
else is rejected with a ``validation`` :class:`~logstead.models.result.Result`
whose ``field`` is ``"content_type"`` and whose message names the accepted types.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from logstead.adapters import s3_files
from logstead.models.property import PropertyPhoto
from logstead.models.result import Result
from logstead.repository import keys

if TYPE_CHECKING:
    from logstead.adapters.s3_files import S3FileAdapter
    from logstead.repository.dynamo_repo import DynamoRepository


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "PresignedUpload",
    "PhotoWithUrl",
    "PhotoService",
]


# --- Content-type allow-list (Requirement 4.2) -------------------------------
#
# The accepted image types for property photos. Matches the design's example
# set (JPEG, PNG, WebP, HEIC) plus HEIF, HEIC's sibling container that modern
# phone cameras also emit. Comparison is case-insensitive (see _normalize).
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
    }
)


def _accepted_types_message() -> str:
    """A human-readable, stable listing of the accepted image content types."""
    return ", ".join(sorted(ALLOWED_CONTENT_TYPES))


def _normalize(content_type: str | None) -> str:
    """Lowercase and trim a declared content type for allow-list comparison.

    A missing/blank content type normalizes to the empty string, which is never
    in the allow-list, so it is rejected like any other unaccepted type.
    """
    return (content_type or "").strip().lower()


@dataclass(frozen=True)
class PresignedUpload:
    """The result of a successful :meth:`PhotoService.request_upload`.

    Carries everything the caller needs to complete a direct-to-S3 upload and to
    render the newly tracked photo:

    Attributes:
        upload_url: A pre-signed S3 **PUT** URL the browser uploads the bytes to.
            The URL is bound to ``photo.content_type``.
        photo: The persisted :class:`PropertyPhoto` metadata (id, s3_key,
            content_type, original_filename, uploaded_at).
    """

    upload_url: str
    photo: PropertyPhoto


class PhotoService:
    """Application service for property photos (Requirement 4).

    Args:
        repo: The single-table DynamoDB repository for metadata persistence.
        files: The S3 file adapter for pre-signed URL issuance and object delete.
    """

    def __init__(self, repo: "DynamoRepository", files: "S3FileAdapter") -> None:
        self._repo = repo
        self._files = files

    # --- Upload (Requirements 4.1, 4.2) --------------------------------------

    def request_upload(
        self, property_id: str, filename: str, content_type: str
    ) -> Result[PresignedUpload]:
        """Authorize a photo upload and record its metadata.

        Validates ``content_type`` against :data:`ALLOWED_CONTENT_TYPES` *first*;
        an unaccepted type is rejected with a ``validation`` failure identifying
        the ``content_type`` field and naming the accepted types (Requirement
        4.2) — no S3 URL is issued and no metadata is written. For an accepted
        type, this builds the photo's S3 key, persists a :class:`PropertyPhoto`
        metadata item under the property partition (Requirement 4.1), and returns
        a pre-signed PUT URL bound to that key and content type together with the
        stored metadata.

        Args:
            property_id: The property the photo is associated with.
            filename: The original client filename (kept for display/download).
            content_type: The declared MIME type of the image being uploaded.

        Returns:
            ``Result[PresignedUpload]`` — success with the upload URL and stored
            metadata, or a ``validation`` failure for a disallowed content type.
        """
        normalized = _normalize(content_type)
        if normalized not in ALLOWED_CONTENT_TYPES:
            return Result.failure(
                "validation",
                "Unsupported image type. Accepted types: "
                f"{_accepted_types_message()}.",
                field="content_type",
            )

        photo_id = str(uuid.uuid4())
        # Namespace the S3 key by photo id so distinct uploads never collide even
        # when the original filenames match: photos/<propertyId>/<photoId>/<name>.
        s3_key = s3_files.photo_key(property_id, f"{photo_id}/{filename}")
        photo = PropertyPhoto(
            id=photo_id,
            property_id=property_id,
            s3_key=s3_key,
            content_type=normalized,
            original_filename=filename,
            uploaded_at=_now_iso(),
        )

        self._repo.put_item(_to_item(photo))
        upload_url = self._files.presigned_put_url(s3_key, normalized)
        return Result.success(PresignedUpload(upload_url=upload_url, photo=photo))

    # --- List (Requirement 4.3) ----------------------------------------------

    def list_photos(self, property_id: str) -> Result[list[PhotoWithUrl]]:
        """List all photos associated with a property, each with a display URL.

        Queries the property partition for ``PHOTO#`` items (Requirement 4.3) and
        pairs each :class:`PropertyPhoto` with a pre-signed **GET** URL so the
        browser can render it directly from S3. Returns an empty list when the
        property has no photos.
        """
        items = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.photo_list_prefix(),
        )
        photos: list[PhotoWithUrl] = []
        for item in items:
            photo = _from_item(item)
            photos.append(
                PhotoWithUrl(
                    photo=photo,
                    display_url=self._files.presigned_get_url(photo.s3_key),
                )
            )
        return Result.success(photos)

    # --- Delete (Requirement 4.4) --------------------------------------------

    def delete_photo(self, property_id: str, photo_id: str) -> Result[None]:
        """Delete a photo's S3 object and its DynamoDB metadata item.

        Looks up the metadata item to resolve the S3 key; a missing photo yields
        a ``not_found`` failure (Requirement 4.4). When present, this removes
        **both** the S3 object and the metadata item so the photo is fully
        dissociated from the property. The S3 delete happens first (it is
        idempotent), then the metadata item is removed.
        """
        pk = keys.property_scoped_pk(property_id)
        sk = keys.photo_sk(photo_id)
        item = self._repo.get_item(pk, sk)
        if item is None:
            return Result.failure(
                "not_found",
                "Photo not found.",
                field="photo_id",
            )

        photo = _from_item(item)
        self._files.delete_object(photo.s3_key)
        self._repo.delete_item(pk, sk)
        return Result.success(None)


@dataclass(frozen=True)
class PhotoWithUrl:
    """A stored photo paired with a pre-signed GET URL for display (4.3)."""

    photo: PropertyPhoto
    display_url: str


# --- Serialization boundary --------------------------------------------------
#
# The stored item uses the design's camelCase attribute names (design.md
# "PropertyPhoto": s3Key, contentType, originalFilename, uploadedAt). ``id`` is
# stored so reads reconstruct the photo without re-parsing the key.

def _to_item(photo: PropertyPhoto) -> dict[str, Any]:
    """Render a :class:`PropertyPhoto` as its DynamoDB item."""
    return {
        "PK": keys.property_scoped_pk(photo.property_id),
        "SK": keys.photo_sk(photo.id),
        "id": photo.id,
        "propertyId": photo.property_id,
        "s3Key": photo.s3_key,
        "contentType": photo.content_type,
        "originalFilename": photo.original_filename,
        "uploadedAt": photo.uploaded_at,
    }


def _from_item(item: dict[str, Any]) -> PropertyPhoto:
    """Reconstruct a :class:`PropertyPhoto` from a stored item."""
    return PropertyPhoto(
        id=str(item["id"]),
        property_id=str(item["propertyId"]),
        s3_key=str(item["s3Key"]),
        content_type=str(item["contentType"]),
        original_filename=str(item["originalFilename"]),
        uploaded_at=(
            str(item["uploadedAt"]) if item.get("uploadedAt") is not None else None
        ),
    )


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (upload timestamp)."""
    return datetime.now(timezone.utc).isoformat()
