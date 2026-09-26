"""Property domain models.

Covers the ``Property`` entity, its optional ``PropertyDetails`` (a sparse,
RentCast-driven field set where every field is individually optional),
per-tax-year usage days, and property photos.

Money fields are typed as ``decimal.Decimal``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class PropertyInput:
    """Input to create or edit a property (Requirement 2.1, 2.2, 2.4).

    ``name`` and ``address_text`` are validated as non-blank by the service
    layer; ``property_type`` is optional at the model level. ``details`` carries
    the optional, RentCast-driven :class:`PropertyDetails` a caller may pass at
    creation time so they are persisted alongside the property; it is never
    required and never gates creation (Requirement 3.7).
    """

    name: str
    address_text: str
    property_type: str | None = None
    details: "PropertyDetails | None" = None


@dataclass
class Property:
    """A rental property owned by the LLC (Requirement 2).

    Attributes:
        id: The property identifier.
        user_id: The owning user's Cognito ``sub``.
        name: Display name.
        address_text: Free-text address used for enrichment and display.
        property_type: Optional property type (e.g., single family).
        created_at: ISO-8601 creation timestamp.
        updated_at: ISO-8601 last-update timestamp.
        details: Optional stored :class:`PropertyDetails`, populated by
            ``PropertyService.get`` when a DETAILS row exists; ``None`` on the
            list/META rows and whenever no details were persisted.
    """

    id: str
    user_id: str
    name: str
    address_text: str
    property_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    details: "PropertyDetails | None" = None


@dataclass
class PropertyFeatures:
    """Nested property features map within ``PropertyDetails``.

    Every field is optional; a field is populated only when a provider
    (RentCast) supplies a value (Requirements 3.8, 12.1, 12.2).

    Descriptive ``*_type`` fields carry the human-readable string RentCast
    provides (e.g. ``heating_type="Forced Air"``), while the paired boolean
    presence flags (``heating``, ``cooling``, ``garage``, ``pool``,
    ``fireplace``) record whether the feature is present. Keeping them
    separate avoids rendering a boolean as the string ``"True"``.
    """

    architecture_type: str | None = None
    exterior_type: str | None = None
    foundation_type: str | None = None
    roof_type: str | None = None
    view_type: str | None = None

    heating: bool | None = None
    heating_type: str | None = None
    cooling: bool | None = None
    cooling_type: str | None = None
    garage: bool | None = None
    garage_spaces: int | None = None
    garage_type: str | None = None
    pool: bool | None = None
    pool_type: str | None = None
    fireplace: bool | None = None
    fireplace_type: str | None = None

    floor_count: int | None = None
    room_count: int | None = None
    unit_count: int | None = None


@dataclass
class TaxAssessment:
    """A single year's tax assessment (Requirement 12.1).

    ``year`` is the assessment year; the money fields are ``Decimal`` (stored
    as two-decimal strings) and each is individually optional.
    """

    year: int
    value: Decimal | None = None
    land: Decimal | None = None
    improvements: Decimal | None = None


@dataclass
class PropertyTax:
    """A single year's property-tax total (Requirement 12.1).

    ``year`` is the tax year; ``total`` is the money amount for that year.
    """

    year: int
    total: Decimal | None = None


@dataclass
class SaleEvent:
    """A single entry in a property's sale history (Requirement 12.1).

    ``date`` is the ISO-8601 date string of the event, ``price`` the money
    amount, and ``event`` the event label (e.g. ``"Sale"``).
    """

    date: str | None = None
    price: Decimal | None = None
    event: str | None = None


@dataclass
class HoaDetails:
    """HOA information for a property (Requirement 12.1).

    ``fee`` is the monthly HOA fee as a money ``Decimal``.
    """

    fee: Decimal | None = None


@dataclass
class PropertyOwner:
    """Ownership information for a property (Requirement 12.1).

    ``names`` lists the owner name(s), ``type`` is the owner classification
    (e.g. ``"Individual"`` / ``"Organization"``), and ``occupied`` records
    the owner-occupied flag when RentCast provides it.
    """

    names: list[str] = field(default_factory=list)
    type: str | None = None
    occupied: bool | None = None


@dataclass
class PropertyDetails:
    """Sparse, RentCast-driven property details (Requirements 2.9, 3.8, 12.1).

    Every field is individually optional and is populated only when a value
    is available; absent fields are reported as unset and are never written
    to storage. The full field set mirrors what a RentCast Property_Record
    can return, plus a nested :class:`PropertyFeatures` map, year-keyed tax
    assessments / property taxes, sale history, HOA, and owner information.
    """

    # Address group
    formatted_address: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    county: str | None = None

    # Geo
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    # Structure
    property_type: str | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    living_area_sqft: int | None = None
    lot_size: Decimal | None = None
    year_built: int | None = None

    # Parcel / legal
    assessor_id: str | None = None
    legal_description: str | None = None
    subdivision: str | None = None
    zoning: str | None = None

    # Last sale (top-level)
    last_sale_date: str | None = None
    last_sale_price: Decimal | None = None

    # Nested features map
    features: PropertyFeatures = field(default_factory=PropertyFeatures)

    # HOA / owner
    hoa: HoaDetails | None = None
    owner: PropertyOwner | None = None

    # Year-keyed history rolled up into ordered lists
    tax_assessments: list[TaxAssessment] = field(default_factory=list)
    property_taxes: list[PropertyTax] = field(default_factory=list)
    sale_history: list[SaleEvent] = field(default_factory=list)


@dataclass(frozen=True)
class AddressSuggestion:
    """A candidate address surfaced as the user types (Requirements 3.1).

    Presented by the address-autocomplete adapter so the user can pick the
    address to hand to RentCast for enrichment. Only a clean, human-readable
    address string is required; ``provider_place_id`` carries the geocoding
    provider's opaque identifier when one is available (e.g., a Google Places
    ``place_id`` or an Amazon Location Service ``PlaceId``), which callers may
    later use to fetch full place details.
    """

    formatted_address: str
    provider_place_id: str | None = None


@dataclass
class PropertyUsageYear:
    """Fair-rental and personal-use days for a property in a tax year.

    Stored per (property, tax_year) and surfaced in the Schedule E report
    header (Requirements 2.8, 10.2).
    """

    property_id: str
    tax_year: int
    fair_rental_days: int
    personal_use_days: int


@dataclass
class PropertyPhoto:
    """Metadata for a property photo; the binary lives in S3 (Requirement 4)."""

    id: str
    property_id: str
    s3_key: str
    content_type: str
    original_filename: str
    uploaded_at: str | None = None
