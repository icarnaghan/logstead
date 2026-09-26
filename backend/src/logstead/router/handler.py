"""API Lambda entrypoint: the handler / router (design "Router (all requirements)").

This is the single AWS Lambda entry point behind the API Gateway **HTTP API**
(payload format v2, JWT authorizer). It is deliberately thin: it owns transport
concerns only — parsing the proxy event, resolving the authenticated user,
matching the request to a route, extracting path params / query / JSON body,
constructing the relevant application service(s), invoking one service method,
and serializing the returned :class:`~logstead.models.result.Result` into an
HTTP response. **No business rules live here** (design "Handler / router");
validation, category mapping, depreciation math, and aggregation all stay in the
services.

Request/response contract
--------------------------
* Input is an API Gateway HTTP API v2 proxy event. The HTTP method and path come
  from ``event["requestContext"]["http"]`` (with a fallback to top-level
  ``httpMethod``/``rawPath`` for v1-shaped test events). The body is JSON when
  present (``isBase64Encoded`` bodies are decoded first). The query string is
  read from ``queryStringParameters``.
* Protected routes require the verified Cognito identity that API Gateway's JWT
  authorizer placed on the request context; :func:`logstead.services.auth.current_user`
  reads it and raises :class:`~logstead.services.auth.AuthError` when it is
  absent — which the router maps to ``401``. The ``GET /categories`` route is the
  one public route (static reference data) and does not require a user.
* Output is a proxy response dict: ``{"statusCode", "headers", "body"}`` with a
  JSON body and ``Content-Type: application/json``.

Result → HTTP mapping
---------------------
Success results become ``200`` (or ``201`` for resource creation) with the value
serialized as JSON. Typed errors map by ``kind``:

    validation   -> 400   (the offending ``field`` is included in the body)
    not_found    -> 404
    conflict     -> 409
    unavailable  -> 503
    unauthorized -> 401

An unmatched route is ``404``; a missing/invalid identity is ``401``; any
unhandled exception is ``500`` with a generic message (no stack trace or
internal detail leaks to the client).

Money serialization (design "Money is exact")
----------------------------------------------
Monetary amounts are ``decimal.Decimal`` in code and are rendered as **two-decimal
strings** in JSON responses (money as strings is the safe choice — it never loses
precision and never becomes a float). Non-money ``Decimal`` values (e.g. an asset
``recovery_period_years`` such as ``27.5``, or a latitude) are rendered as their
plain decimal string too, so no ``Decimal`` ever reaches ``json`` as a float.

Wiring (design "Deployment" / env config)
------------------------------------------
The repository, S3 adapter, and external adapters are constructed **once per
container** from environment configuration (``TABLE_NAME``, ``FILES_BUCKET``,
``AWS_REGION``, ``RENTCAST_API_KEY``) and reused across
invocations. boto3 clients are created lazily on first use so importing this
module never requires AWS credentials (tests import it freely and inject their
own wiring via :func:`configure`).
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import fields, is_dataclass
from decimal import Decimal
from typing import Any, Callable

from logstead.models.result import Error, Result
from logstead.services.auth import AuthError, current_user

__all__ = ["handler", "configure", "reset_wiring"]


# --- Result-kind → HTTP status mapping --------------------------------------

#: Maps a typed-error ``kind`` to its HTTP status code (design "Error Handling").
_ERROR_STATUS: dict[str, int] = {
    "validation": 400,
    "not_found": 404,
    "conflict": 409,
    "unavailable": 503,
    "unauthorized": 401,
}

_JSON_HEADERS: dict[str, str] = {"Content-Type": "application/json"}


# --- JSON serialization (dataclasses + Decimal money as strings) ------------


def _to_jsonable(value: Any) -> Any:
    """Recursively convert a value into a JSON-serializable structure.

    * ``Decimal`` → string (money and any other decimal render as their exact
      decimal string, never a float, so precision is preserved; design "Money is
      exact").
    * dataclass instances → dict of their fields (recursively converted), with
      snake_case field names preserved as-is.
    * lists/tuples/sets → lists (recursively converted).
    * dicts → dicts (values recursively converted; keys coerced to strings).
    * primitives (str, int, bool, None) → themselves.
    """
    if isinstance(value, Decimal):
        # Fixed decimal string. ``str(Decimal)`` never emits scientific notation
        # for the ranges Logstead uses and preserves the stored precision.
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    return value


def _response(status: int, body: Any) -> dict[str, Any]:
    """Build an API Gateway proxy response with a JSON body."""
    return {
        "statusCode": status,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps(_to_jsonable(body)),
    }


def _error_body(error: Error) -> dict[str, Any]:
    """Render a typed :class:`Error` into the response body shape.

    Includes the offending ``field`` when the error is field-specific so the SPA
    can render the message adjacent to that field (design "Validation errors").
    """
    body: dict[str, Any] = {"error": error.kind, "message": error.message}
    if error.field is not None:
        body["field"] = error.field
    return body


def _result_response(result: Result[Any], *, success_status: int = 200) -> dict[str, Any]:
    """Serialize a service :class:`Result` into an HTTP proxy response.

    Success → ``success_status`` (200 by default, 201 for creation) with the
    value as JSON. Error → the status mapped from its ``kind`` with an error body.
    """
    if result.is_ok:
        return _response(success_status, result.value)
    error = result.error
    assert error is not None  # a non-ok Result always carries an error
    status = _ERROR_STATUS.get(error.kind, 400)
    return _response(status, _error_body(error))


# --- Event parsing -----------------------------------------------------------


class _RouterError(Exception):
    """Internal signal to short-circuit dispatch with a specific status/body.

    Used for request-shape problems the router itself owns (a 400 for a malformed
    JSON body). Business validation is never raised — it flows back as a
    ``Result`` from the service.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _method_and_path(event: dict[str, Any]) -> tuple[str, str]:
    """Extract the HTTP method and path from an HTTP API v2 (or v1) event.

    HTTP API v2 places them under ``requestContext.http`` (``method``/``path``);
    a v1-shaped or hand-built test event may use top-level ``httpMethod`` and
    ``rawPath``/``path``. Both are supported so the handler is easy to drive from
    tests. The path is normalized to strip a trailing slash (except root).
    """
    method = ""
    path = ""

    request_context = event.get("requestContext")
    if isinstance(request_context, dict):
        http = request_context.get("http")
        if isinstance(http, dict):
            method = str(http.get("method", "") or "")
            path = str(http.get("path", "") or "")

    if not method:
        method = str(event.get("httpMethod", "") or "")
    if not path:
        path = str(event.get("rawPath", event.get("path", "")) or "")

    method = method.upper()

    # A non-$default HTTP API stage (e.g. "prod") prefixes the request path with
    # the stage name (path becomes "/prod/categories"). The route table is keyed
    # on stage-relative paths ("/categories"), so strip a leading "/<stage>" when
    # the event carries a stage that the path starts with.
    stage = ""
    if isinstance(request_context, dict):
        stage = str(request_context.get("stage", "") or "")
    if stage and stage != "$default":
        prefix = "/" + stage
        if path == prefix:
            path = "/"
        elif path.startswith(prefix + "/"):
            path = path[len(prefix):]

    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"
    return method, path


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Parse the request body into a dict (empty dict when there is no body).

    Handles base64-encoded bodies (``isBase64Encoded``). A present-but-malformed
    JSON body raises a :class:`_RouterError` (→ 400). A body that parses to a
    non-object (e.g. a bare list or string) is also rejected, since every
    Logstead write route expects a JSON object.
    """
    raw = event.get("body")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, (dict, list)):
        # Already-parsed body (some test harnesses pass a dict directly).
        parsed: Any = raw
    else:
        text = raw
        if event.get("isBase64Encoded"):
            try:
                text = base64.b64decode(raw).decode("utf-8")
            except Exception as exc:  # noqa: BLE001 - any decode failure is a 400
                raise _RouterError(400, "Request body could not be decoded.") from exc
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise _RouterError(400, "Request body is not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise _RouterError(400, "Request body must be a JSON object.")
    return parsed


def _query(event: dict[str, Any]) -> dict[str, str]:
    """Return the query-string parameters as a ``{str: str}`` dict (never None)."""
    params = event.get("queryStringParameters")
    if not isinstance(params, dict):
        return {}
    return {str(k): str(v) for k, v in params.items() if v is not None}


def _int_param(value: str | None, name: str) -> int:
    """Parse an integer query/path value, raising a 400 :class:`_RouterError`.

    Used for ``taxYear`` and day-count query params so a bad value becomes a
    clean 400 rather than an unhandled 500.
    """
    if value is None or str(value).strip() == "":
        raise _RouterError(400, f"'{name}' is required.")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise _RouterError(400, f"'{name}' must be an integer.") from exc


# --- Path templating ---------------------------------------------------------


def _match_path(template: str, path: str) -> dict[str, str] | None:
    """Match a request ``path`` against a route ``template``; return path params.

    Templates use ``{name}`` segments, e.g.
    ``/properties/{propertyId}/transactions/{transactionId}``. On a match the
    captured params are returned as a dict (empty when the template is static);
    ``None`` when the path does not match (different length or a literal segment
    mismatch). Trailing slashes are already normalized away by
    :func:`_method_and_path`.
    """
    t_parts = [p for p in template.split("/") if p != ""]
    p_parts = [p for p in path.split("/") if p != ""]
    if len(t_parts) != len(p_parts):
        return None
    params: dict[str, str] = {}
    for t_seg, p_seg in zip(t_parts, p_parts):
        if t_seg.startswith("{") and t_seg.endswith("}"):
            params[t_seg[1:-1]] = p_seg
        elif t_seg != p_seg:
            return None
    return params


# --- Container-scoped wiring -------------------------------------------------
#
# The repository and adapters are expensive to build and safe to reuse across
# invocations, so they are cached at module scope and created lazily on first
# use. ``configure`` lets tests inject a fully wired context (moto-backed repo /
# adapters) without any environment or boto3 dependency.


class _Wiring:
    """Holds the constructed repository and adapters for a container.

    Built lazily from environment configuration, or injected wholesale by
    :func:`configure` in tests. All service objects are constructed per request
    from this wiring (services are cheap, stateless value objects around the
    repo/adapters).
    """

    def __init__(self, repo: Any, files: Any, rentcast: Any, autocomplete: Any) -> None:
        self.repo = repo
        self.files = files
        self.rentcast = rentcast
        self.autocomplete = autocomplete


_WIRING: _Wiring | None = None


def configure(
    *,
    repo: Any,
    files: Any = None,
    rentcast: Any = None,
    autocomplete: Any = None,
) -> None:
    """Inject the router's wiring (repository + adapters), replacing any default.

    Tests call this with moto-backed collaborators so the handler runs entirely
    against in-memory AWS with no environment or credentials. Adapters not needed
    by the routes under test may be omitted (``None``); a route that needs a
    missing adapter surfaces a clean 503 rather than crashing.
    """
    global _WIRING
    _WIRING = _Wiring(repo=repo, files=files, rentcast=rentcast, autocomplete=autocomplete)


def reset_wiring() -> None:
    """Clear cached wiring so the next request rebuilds from the environment.

    Primarily a test aid to isolate cases that :func:`configure` different
    wirings.
    """
    global _WIRING
    _WIRING = None


def _env(name: str, default: str | None = None) -> str | None:
    """Read an environment variable (thin indirection for testability)."""
    return os.environ.get(name, default)


def _resolve_rentcast_key() -> str | None:
    """Resolve the RentCast API key, preferring SSM Parameter Store.

    The key is a secret, so it lives in an SSM SecureString parameter rather
    than a plaintext Lambda env var (aws-cloudformation: never store secrets in
    plain env vars/parameters). ``RENTCAST_API_KEY_PARAM`` names that parameter;
    it is fetched once per container with decryption. A direct
    ``RENTCAST_API_KEY`` env var still wins when present, so local runs and tests
    need no SSM. Any lookup failure degrades to ``None`` (enrichment then 503s),
    never crashing wiring.
    """
    direct = _env("RENTCAST_API_KEY")
    if direct:
        return direct
    param_name = _env("RENTCAST_API_KEY_PARAM")
    if not param_name:
        return None
    try:
        import boto3  # local import: keep import-time AWS-free

        region = _env("AWS_REGION") or _env("AWS_DEFAULT_REGION")
        ssm = boto3.client("ssm", region_name=region)
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
        value = resp.get("Parameter", {}).get("Value")
        return value or None
    except Exception:  # noqa: BLE001 - any SSM failure => no key (enrichment 503s)
        return None


def _build_wiring_from_env() -> _Wiring:
    """Construct the repository and adapters from environment configuration.

    boto3 clients are imported and created here, on first use, so importing this
    module never requires AWS credentials. Requires ``TABLE_NAME``; the S3 bucket
    and external API keys are optional (routes needing an unconfigured adapter
    degrade to 503 / empty behavior at the service layer).
    """
    import boto3  # local import: avoid an import-time AWS dependency

    from logstead.adapters.autocomplete import AutocompleteAdapter
    from logstead.adapters.rentcast import RentCastAdapter
    from logstead.adapters.s3_files import S3FileAdapter
    from logstead.repository.dynamo_repo import DynamoRepository

    region = _env("AWS_REGION") or _env("AWS_DEFAULT_REGION")
    table_name = _env("TABLE_NAME") or "Logstead"
    bucket = _env("FILES_BUCKET") or _env("BUCKET")

    ddb = boto3.client("dynamodb", region_name=region)
    repo = DynamoRepository(ddb, table_name)

    files = None
    if bucket:
        s3 = boto3.client("s3", region_name=region)
        files = S3FileAdapter(s3, bucket)

    rentcast = RentCastAdapter(_resolve_rentcast_key())
    # Autocomplete uses Amazon Location Service via the Lambda's IAM role
    # (SigV4); no API key is needed. The client is created lazily.
    autocomplete = AutocompleteAdapter()
    return _Wiring(repo=repo, files=files, rentcast=rentcast, autocomplete=autocomplete)


def _wiring() -> _Wiring:
    """Return the container-scoped wiring, building it from env on first use."""
    global _WIRING
    if _WIRING is None:
        _WIRING = _build_wiring_from_env()
    return _WIRING


def _require_files(wiring: _Wiring) -> Any:
    """Return the S3 file adapter or raise a 503 when file storage is unconfigured."""
    if wiring.files is None:
        raise _RouterError(503, "File storage is not configured.")
    return wiring.files


# --- Service constructors (per request) --------------------------------------
#
# Services are constructed fresh per request from the shared wiring. They are
# thin, stateless wrappers around the repo/adapters (plus the resolved user for
# the property service), so per-request construction is cheap and keeps user
# scoping explicit.


def _property_service(wiring: _Wiring, user: Any) -> Any:
    from logstead.services.property import PropertyService

    return PropertyService(wiring.repo, user)


def _transaction_service(wiring: _Wiring) -> Any:
    from logstead.services.transaction import TransactionService

    return TransactionService(wiring.repo, _require_files(wiring))


def _depreciation_service(wiring: _Wiring) -> Any:
    from logstead.services.depreciation import DepreciationService

    return DepreciationService(wiring.repo)


def _photo_service(wiring: _Wiring) -> Any:
    from logstead.services.photo import PhotoService

    return PhotoService(wiring.repo, _require_files(wiring))


def _import_service(wiring: _Wiring) -> Any:
    from logstead.services.expense_import import ExpenseImportService

    return ExpenseImportService(wiring.repo)


def _reporting_service(wiring: _Wiring, user: Any) -> Any:
    from logstead.services.report import ReportingService

    return ReportingService(
        _transaction_service(wiring),
        _depreciation_service(wiring),
        _property_service(wiring, user),
    )


def _enrichment_service(wiring: _Wiring) -> Any:
    from logstead.services.enrichment import AddressEnrichmentService

    if wiring.autocomplete is None or wiring.rentcast is None:
        raise _RouterError(503, "Address enrichment is not configured.")
    return AddressEnrichmentService(wiring.autocomplete, wiring.rentcast)


# --- Input mapping helpers ---------------------------------------------------


def _property_input(body: dict[str, Any]) -> Any:
    """Map a JSON body to a :class:`PropertyInput` (accepts snake or camel case).

    An optional ``details`` object in the body is deserialized into a
    :class:`PropertyDetails` via the same JSON/dict parser used for storage
    (money strings → two-decimal ``Decimal``), so a caller can persist RentCast
    enrichment at creation time. A non-object ``details`` value is ignored.
    """
    from logstead.models.property import PropertyInput
    from logstead.models.property_details_json import details_from_dict

    raw_details = body.get("details")
    details = (
        details_from_dict(raw_details) if isinstance(raw_details, dict) else None
    )

    return PropertyInput(
        name=body.get("name"),
        address_text=body.get("address_text", body.get("addressText")),
        property_type=body.get("property_type", body.get("propertyType")),
        details=details,
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    """Coerce a JSON amount (string or number) to ``Decimal``; ``None`` when absent.

    Money arrives as a string in requests (the SPA sends money as strings). A bad
    value raises a 400 :class:`_RouterError` so it never reaches the service as a
    surprise type.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - any bad numeric literal is a 400
        raise _RouterError(400, "Amount is not a valid number.") from exc


def _transaction_input(body: dict[str, Any], property_id: str) -> Any:
    """Map a JSON body + path property id to a :class:`TransactionInput`."""
    from logstead.models.transaction import TransactionInput

    return TransactionInput(
        property_id=property_id,
        date=body.get("date"),
        amount=_decimal_or_none(body.get("amount")),
        type=body.get("type"),
        category_id=body.get("category_id", body.get("categoryId")),
        description=body.get("description"),
    )


def _asset_input(body: dict[str, Any], property_id: str) -> Any:
    """Map a JSON body + path property id to an :class:`AssetInput`."""
    from logstead.models.depreciation import AssetInput

    recovery = body.get("recovery_period_years", body.get("recoveryPeriodYears"))
    return AssetInput(
        property_id=property_id,
        description=body.get("description"),
        cost_basis=_decimal_or_none(body.get("cost_basis", body.get("costBasis"))),
        placed_in_service_date=body.get(
            "placed_in_service_date", body.get("placedInServiceDate")
        ),
        recovery_period_years=(
            Decimal(str(recovery)) if recovery not in (None, "") else None
        ),
    )


# --- Route handlers ----------------------------------------------------------
#
# Each handler receives the resolved wiring, the authenticated user (or None for
# the public categories route), the captured path params, the parsed body, and
# the query dict. It calls exactly one service method and returns an HTTP proxy
# response. No handler contains business rules.


def _list_categories(wiring: _Wiring, user: Any, params, body, query) -> dict[str, Any]:
    from logstead.services.category import list_categories

    return _response(200, list_categories(wiring.repo))


# -- Address enrichment --

def _suggest_addresses(wiring: _Wiring, user, params, body, query) -> dict[str, Any]:
    service = _enrichment_service(wiring)
    suggestions = service.suggest_addresses(query.get("q", query.get("query", "")))
    return _response(200, suggestions)


def _unit_addresses(wiring: _Wiring, user, params, body, query) -> dict[str, Any]:
    service = _enrichment_service(wiring)
    address = query.get("address", query.get("q", ""))
    return _response(200, service.unit_addresses(str(address or "")))


def _enrich_address(wiring: _Wiring, user, params, body, query) -> dict[str, Any]:
    service = _enrichment_service(wiring)
    address = body.get("address", body.get("address_text", body.get("addressText", "")))
    return _response(200, service.enrich(str(address or "")))


# -- Properties --

def _create_property(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _result_response(service.create(_property_input(body)), success_status=201)


def _list_properties(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _response(200, service.list())


def _get_property(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _result_response(service.get(params["propertyId"]))


def _update_property(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _result_response(service.update(params["propertyId"], _property_input(body)))


def _delete_property(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _result_response(service.delete(params["propertyId"]))


def _set_usage_days(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    tax_year = _int_param(str(body.get("tax_year", body.get("taxYear"))), "taxYear")
    fair = _int_param(
        str(body.get("fair_rental_days", body.get("fairRentalDays"))),
        "fairRentalDays",
    )
    personal = _int_param(
        str(body.get("personal_use_days", body.get("personalUseDays"))),
        "personalUseDays",
    )
    return _result_response(
        service.set_usage_days(params["propertyId"], tax_year, fair, personal)
    )


def _get_usage_days(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    tax_year = _int_param(query.get("taxYear"), "taxYear")
    return _result_response(service.get_usage_days(params["propertyId"], tax_year))


def _get_note(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    result = service.get_note(params["propertyId"])
    if not result.is_ok:
        return _result_response(result)
    return _response(200, {"text": result.value})


def _set_note(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    text = str(body.get("text", "") or "")
    result = service.set_note(params["propertyId"], text)
    if not result.is_ok:
        return _result_response(result)
    return _response(200, {"text": result.value})


# -- Property photos --

def _request_photo_upload(wiring, user, params, body, query) -> dict[str, Any]:
    service = _photo_service(wiring)
    return _result_response(
        service.request_upload(
            params["propertyId"],
            str(body.get("filename", "")),
            str(body.get("content_type", body.get("contentType", ""))),
        ),
        success_status=201,
    )


def _list_photos(wiring, user, params, body, query) -> dict[str, Any]:
    service = _photo_service(wiring)
    return _result_response(service.list_photos(params["propertyId"]))


def _delete_photo(wiring, user, params, body, query) -> dict[str, Any]:
    service = _photo_service(wiring)
    return _result_response(service.delete_photo(params["propertyId"], params["photoId"]))


# -- Transactions --

def _create_transaction(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.create(_transaction_input(body, params["propertyId"])),
        success_status=201,
    )


def _list_transactions(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    tax_year = _int_param(query.get("taxYear"), "taxYear") if query.get("taxYear") else None
    return _result_response(service.list_for_property(params["propertyId"], tax_year))


def _get_transaction(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.get(params["propertyId"], params["transactionId"])
    )


def _update_transaction(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.update(
            params["propertyId"],
            params["transactionId"],
            _transaction_input(body, params["propertyId"]),
        )
    )


def _delete_transaction(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.delete(params["propertyId"], params["transactionId"])
    )


def _attach_receipt(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.attach_receipt(
            params["propertyId"],
            params["transactionId"],
            str(body.get("filename", "")),
            str(body.get("content_type", body.get("contentType", ""))),
        ),
        success_status=201,
    )


def _list_receipts(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.list_receipts(params["propertyId"], params["transactionId"])
    )


def _delete_receipt(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.delete_receipt(
            params["propertyId"], params["transactionId"], params["documentId"]
        )
    )


# -- Depreciable assets --

def _create_asset(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _result_response(
        service.create_asset(_asset_input(body, params["propertyId"])),
        success_status=201,
    )


def _list_assets(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _response(200, service.list_assets(params["propertyId"]))


def _get_asset(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _result_response(service.get_asset(params["propertyId"], params["assetId"]))


def _update_asset(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _result_response(
        service.update_asset(
            params["propertyId"], params["assetId"], _asset_input(body, params["propertyId"])
        )
    )


def _delete_asset(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _result_response(
        service.delete_asset(params["propertyId"], params["assetId"])
    )


def _asset_schedule(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _response(
        200, service.schedule_for(params["propertyId"], params["assetId"])
    )


# -- Expense imports --

def _create_import(wiring, user, params, body, query) -> dict[str, Any]:
    service = _import_service(wiring)
    property_id = str(body.get("property_id", body.get("propertyId", "")))
    tax_year = _int_param(str(body.get("tax_year", body.get("taxYear"))), "taxYear")
    pdf_bytes = None
    b64 = body.get("pdf_base64", body.get("pdfBase64"))
    if b64:
        try:
            pdf_bytes = base64.b64decode(b64)
        except Exception as exc:  # noqa: BLE001
            raise _RouterError(400, "pdf_base64 could not be decoded.") from exc
    return _result_response(
        service.create_session(
            property_id,
            tax_year,
            pdf_bytes=pdf_bytes,
            pdf_s3_key=body.get("pdf_s3_key", body.get("pdfS3Key")),
            content_type=body.get("content_type", body.get("contentType")),
        ),
        success_status=201,
    )


def _get_import(wiring, user, params, body, query) -> dict[str, Any]:
    service = _import_service(wiring)
    return _result_response(service.get_session(params["sessionId"]))


def _list_drafts(wiring, user, params, body, query) -> dict[str, Any]:
    service = _import_service(wiring)
    return _response(200, service.list_drafts(params["sessionId"]))


def _update_draft(wiring, user, params, body, query) -> dict[str, Any]:
    service = _import_service(wiring)
    return _result_response(
        service.update_draft(params["sessionId"], params["draftId"], body)
    )


def _remove_draft(wiring, user, params, body, query) -> dict[str, Any]:
    service = _import_service(wiring)
    return _result_response(
        service.remove_draft(params["sessionId"], params["draftId"])
    )


def _confirm_import(wiring, user, params, body, query) -> dict[str, Any]:
    service = _import_service(wiring)
    return _result_response(service.confirm(params["sessionId"]))


# -- Reports --

def _property_report(wiring, user, params, body, query) -> dict[str, Any]:
    service = _reporting_service(wiring, user)
    tax_year = _int_param(query.get("taxYear"), "taxYear")
    return _result_response(service.report_for(params["propertyId"], tax_year))


def _combined_report(wiring, user, params, body, query) -> dict[str, Any]:
    service = _reporting_service(wiring, user)
    tax_year = _int_param(query.get("taxYear"), "taxYear")
    ids_param = query.get("propertyIds")
    property_ids = (
        [p for p in ids_param.split(",") if p] if ids_param else None
    )
    return _result_response(service.combined_report(property_ids, tax_year))


# -- Dashboard (guarded: task 15.1 may not be present yet) --

def _dashboard_service_or_503(wiring: _Wiring, user: Any) -> Any:
    """Construct the Dashboard service, or raise 503 if it is not yet available.

    The Dashboard service (task 15.1) is written concurrently and may not be
    importable. Import it lazily so this router imports cleanly regardless, and
    surface a clean 503 when a dashboard route is hit before the service lands.
    """
    try:
        from logstead.services.dashboard import DashboardService  # type: ignore
    except ImportError as exc:
        raise _RouterError(503, "Dashboard is not available yet.") from exc
    # DashboardService composes the property service and the reporting service
    # (it derives each property's income/expense/net from the Schedule E report
    # so the dashboard matches the report exactly).
    return DashboardService(
        _property_service(wiring, user),
        _reporting_service(wiring, user),
    )


def _dashboard_portfolio(wiring, user, params, body, query) -> dict[str, Any]:
    # DashboardService is already scoped to the user via its injected
    # PropertyService, so the summary methods take only an optional tax year.
    service = _dashboard_service_or_503(wiring, user)
    tax_year = _int_param(query.get("taxYear"), "taxYear") if query.get("taxYear") else None
    return _response(200, service.portfolio_summary(tax_year))


def _dashboard_per_property(wiring, user, params, body, query) -> dict[str, Any]:
    service = _dashboard_service_or_503(wiring, user)
    tax_year = _int_param(query.get("taxYear"), "taxYear") if query.get("taxYear") else None
    return _response(200, service.per_property_summary(tax_year))


# --- Route table -------------------------------------------------------------
#
# Ordered (METHOD, path-template) -> handler. Path templates use {name} segments.
# ``public`` routes skip the identity requirement (only the static category
# catalog). Matching is first-hit over the ordered list; more specific templates
# with the same segment count are disambiguated by literal segments in
# ``_match_path`` (e.g. ``.../transactions/{id}/receipts`` vs a 5-segment shape).

_Handler = Callable[[_Wiring, Any, dict, dict, dict], dict]

# Each entry: (method, template, handler, public)
_ROUTES: tuple[tuple[str, str, _Handler, bool], ...] = (
    # Categories (public reference data)
    ("GET", "/categories", _list_categories, True),
    # Address enrichment
    ("GET", "/addresses/units", _unit_addresses, False),
    ("GET", "/addresses", _suggest_addresses, False),
    ("POST", "/properties/enrich", _enrich_address, False),
    # Properties
    ("POST", "/properties", _create_property, False),
    ("GET", "/properties", _list_properties, False),
    ("GET", "/properties/{propertyId}", _get_property, False),
    ("PUT", "/properties/{propertyId}", _update_property, False),
    ("DELETE", "/properties/{propertyId}", _delete_property, False),
    ("PUT", "/properties/{propertyId}/usage", _set_usage_days, False),
    ("GET", "/properties/{propertyId}/usage", _get_usage_days, False),
    ("GET", "/properties/{propertyId}/notes", _get_note, False),
    ("PUT", "/properties/{propertyId}/notes", _set_note, False),
    # Property photos
    ("POST", "/properties/{propertyId}/photos", _request_photo_upload, False),
    ("GET", "/properties/{propertyId}/photos", _list_photos, False),
    ("DELETE", "/properties/{propertyId}/photos/{photoId}", _delete_photo, False),
    # Transactions
    ("POST", "/properties/{propertyId}/transactions", _create_transaction, False),
    ("GET", "/properties/{propertyId}/transactions", _list_transactions, False),
    ("GET", "/properties/{propertyId}/transactions/{transactionId}", _get_transaction, False),
    ("PUT", "/properties/{propertyId}/transactions/{transactionId}", _update_transaction, False),
    ("DELETE", "/properties/{propertyId}/transactions/{transactionId}", _delete_transaction, False),
    # Receipts
    ("POST", "/properties/{propertyId}/transactions/{transactionId}/receipts", _attach_receipt, False),
    ("GET", "/properties/{propertyId}/transactions/{transactionId}/receipts", _list_receipts, False),
    ("DELETE", "/properties/{propertyId}/transactions/{transactionId}/receipts/{documentId}", _delete_receipt, False),
    # Depreciable assets
    ("POST", "/properties/{propertyId}/assets", _create_asset, False),
    ("GET", "/properties/{propertyId}/assets", _list_assets, False),
    ("GET", "/properties/{propertyId}/assets/{assetId}", _get_asset, False),
    ("PUT", "/properties/{propertyId}/assets/{assetId}", _update_asset, False),
    ("DELETE", "/properties/{propertyId}/assets/{assetId}", _delete_asset, False),
    ("GET", "/properties/{propertyId}/assets/{assetId}/schedule", _asset_schedule, False),
    # Expense imports
    ("POST", "/imports", _create_import, False),
    ("GET", "/imports/{sessionId}", _get_import, False),
    ("GET", "/imports/{sessionId}/drafts", _list_drafts, False),
    ("PUT", "/imports/{sessionId}/drafts/{draftId}", _update_draft, False),
    ("DELETE", "/imports/{sessionId}/drafts/{draftId}", _remove_draft, False),
    ("POST", "/imports/{sessionId}/confirm", _confirm_import, False),
    # Reports
    ("GET", "/properties/{propertyId}/report", _property_report, False),
    ("GET", "/reports/combined", _combined_report, False),
    # Dashboard
    ("GET", "/dashboard", _dashboard_portfolio, False),
    ("GET", "/dashboard/properties", _dashboard_per_property, False),
)


def _dispatch(
    method: str, path: str
) -> tuple[_Handler, dict[str, str], bool] | None:
    """Find the first route matching ``method`` + ``path``.

    Returns ``(handler, path_params, public)`` on a match, or ``None`` when no
    route matches (→ 404). Order matters only where two templates share a segment
    count; literal-segment matching in :func:`_match_path` keeps
    ``/properties/enrich`` from being captured by ``/properties/{propertyId}``
    because ``enrich`` is placed first in the table.
    """
    for route_method, template, route_handler, public in _ROUTES:
        if route_method != method:
            continue
        params = _match_path(template, path)
        if params is not None:
            return route_handler, params, public
    return None


# --- Entry point -------------------------------------------------------------


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point for the API Gateway HTTP API (design "Router").

    Parses the proxy event, resolves the authenticated user for protected routes,
    dispatches to the matching service method, and serializes the ``Result`` into
    an HTTP proxy response. Unmatched routes yield ``404``; a missing/invalid
    identity yields ``401``; any unexpected exception yields a generic ``500``
    with no internal detail leaked.
    """
    if not isinstance(event, dict):
        return _response(400, {"error": "validation", "message": "Malformed event."})

    method, path = _method_and_path(event)

    # CORS preflight: the browser sends OPTIONS with no Authorization header.
    # API Gateway's auto-CORS attaches the Access-Control-* response headers;
    # the Lambda only needs to answer with a success status and no body. This
    # must happen before route dispatch and the auth check.
    if method.upper() == "OPTIONS":
        return {"statusCode": 204, "headers": {}, "body": ""}

    match = _dispatch(method, path)
    if match is None:
        return _response(404, {"error": "not_found", "message": "No such route."})
    route_handler, params, public = match

    try:
        wiring = _wiring()

        # Resolve identity for protected routes; the categories route is public.
        user = None
        if not public:
            try:
                user = current_user(event)
            except AuthError as exc:
                return _response(
                    401, {"error": "unauthorized", "message": str(exc)}
                )

        body = _parse_body(event)
        query = _query(event)

        return route_handler(wiring, user, params, body, query)
    except _RouterError as exc:
        # Router-owned request-shape problems (bad JSON, bad int, unconfigured
        # adapter). Kind is derived from the status for a consistent body shape.
        kind = {400: "validation", 503: "unavailable"}.get(exc.status, "validation")
        return _response(exc.status, {"error": kind, "message": exc.message})
    except Exception:  # noqa: BLE001 - last-resort guard; never leak internals
        return _response(
            500,
            {"error": "internal", "message": "An unexpected error occurred."},
        )
