"""Item mappers between domain dataclasses and DynamoDB item dicts.

The repository (:mod:`logstead.repository.dynamo_repo`) speaks in plain item
dicts and applies two storage rules: absent (``None``) attributes are dropped so
items stay sparse (Requirements 12.2, 12.3), and money attributes are stored as
two-decimal strings (Requirement 13.3). This module turns the sparse,
provider-driven :class:`~logstead.models.property.PropertyDetails` dataclass into
such an item dict and rebuilds it on read, so present fields round-trip verbatim
and absent fields are reported as unset (Property 4; Requirements 2.9, 3.3, 3.8,
12.1).

``PropertyDetails`` has a nested :class:`~logstead.models.property.PropertyFeatures`
map. Its individually-optional sub-fields are handled the same way: only present
feature sub-fields are written (under a nested ``features`` map), and the map is
omitted entirely when no feature is present. This preserves the sparse contract
one level down as well.

The mappers deliberately do **not** touch DynamoDB key attributes (``PK``/``SK``
and any GSI keys). A caller merges the returned attribute dict with the keys it
builds via :mod:`logstead.repository.keys` before persisting.

Scalar ``Decimal`` fields on ``PropertyDetails`` (``latitude``, ``longitude``,
``bathrooms``, ``lot_size``) are *not* money attributes; they are stored as
DynamoDB numbers and read back as ``Decimal`` by the repository, so they are left
out of the money-attribute set and pass through unchanged.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Mapping

from logstead.models.property import PropertyDetails, PropertyFeatures

__all__ = [
    "FEATURES_ATTR",
    "property_details_to_item",
    "item_to_property_details",
]

#: Attribute name under which the nested feature map is stored.
FEATURES_ATTR = "features"


def _features_to_map(features: PropertyFeatures) -> dict[str, Any]:
    """Return only the present feature sub-fields as a plain dict.

    Absent (``None``) sub-fields are omitted so the stored feature map stays
    sparse (Requirements 12.2, 12.3).
    """
    return {
        f.name: value
        for f in fields(PropertyFeatures)
        if (value := getattr(features, f.name)) is not None
    }


def property_details_to_item(details: PropertyDetails) -> dict[str, Any]:
    """Flatten ``PropertyDetails`` into a sparse DynamoDB attribute dict.

    Every present scalar field becomes a top-level attribute; ``None`` fields are
    omitted. Present feature sub-fields are nested under a ``features`` map, which
    is itself omitted when no feature is present. The result carries no key
    attributes — the caller merges in ``PK``/``SK`` before writing.
    """
    item: dict[str, Any] = {}
    for f in fields(PropertyDetails):
        if f.name == FEATURES_ATTR:
            continue
        value = getattr(details, f.name)
        if value is not None:
            item[f.name] = value

    feature_map = _features_to_map(details.features)
    if feature_map:
        item[FEATURES_ATTR] = feature_map
    return item


def item_to_property_details(item: Mapping[str, Any] | None) -> PropertyDetails:
    """Rebuild ``PropertyDetails`` from a stored attribute dict.

    Attributes absent from ``item`` remain ``None`` on the reconstructed
    dataclass (reported as unset; Requirement 12.3). Key attributes and any other
    unrelated attributes present on the item are ignored. A missing or empty
    ``features`` map yields an all-unset :class:`PropertyFeatures`.
    """
    item = item or {}
    detail_names = {f.name for f in fields(PropertyDetails)} - {FEATURES_ATTR}
    kwargs: dict[str, Any] = {
        name: item[name] for name in detail_names if name in item
    }

    feature_map = item.get(FEATURES_ATTR) or {}
    feature_names = {f.name for f in fields(PropertyFeatures)}
    feature_kwargs = {
        name: feature_map[name] for name in feature_names if name in feature_map
    }
    return PropertyDetails(features=PropertyFeatures(**feature_kwargs), **kwargs)
