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
  absent — which the router maps to ``401``. Every route, including
  ``GET /categories`` (static reference data), requires a user.
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
import functools
import json
import logging
import os
import re
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from typing import Any, Callable, NamedTuple

from logstead.models.result import Error, Result
from logstead.services.auth import AuthError, current_user
from logstead.util.logsafe import exc_summary

__all__ = [
    "handler",
    "configure",
    "reset_wiring",
    "get_wiring",
    "to_jsonable",
    "build_package_service",
]

_log = logging.getLogger(__name__)

# --- Request-shape limits (task 4.2) ------------------------------------------
#
# These bound untrusted input at the trust boundary. They are deliberately far
# above any legitimate value so they only stop abuse (oversized items that would
# exceed the DynamoDB item limit, unbounded loops, key-delimiter injection).

#: Longest string accepted in a JSON body for ordinary routes.
_MAX_STRING_LEN = 10_000
#: Longest list accepted in a JSON body for ordinary routes.
_MAX_LIST_LEN = 1_000
#: Deepest JSON nesting accepted in a JSON body.
_MAX_JSON_DEPTH = 10
#: Largest absolute money/decimal value accepted from a client.
_MAX_ABS_AMOUNT = Decimal("9999999999999.99")
#: Tax-year bounds for path/query/body ``taxYear`` values.
_MIN_TAX_YEAR = 1900
_MAX_TAX_YEAR = 2200
#: Resource ids (path params named ``*Id``) are uuid-like tokens. Rejecting
#: anything else keeps ``#`` (the key delimiter), whitespace and oversize values
#: out of DynamoDB and S3 keys.
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_INT_RE = re.compile(r"^[+-]?[0-9]{1,18}$")


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
    if error.errors:
        body["errors"] = [
            {"field": field, "message": message} for field, message in error.errors
        ]
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

    def __init__(self, status: int, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field


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
        except (json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise _RouterError(400, "Request body is not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise _RouterError(400, "Request body must be a JSON object.")
    return parsed


def _check_body_shape(value: Any, depth: int = 0) -> None:
    """Reject oversized strings/lists and deep nesting in a parsed JSON body.

    Applied to every route except the two that legitimately carry large
    documents (``POST /backup/restore`` and ``POST /imports`` with an inline
    PDF). API Gateway already caps the whole payload (10 MB); these limits stop
    a single field from exceeding the DynamoDB item limit or a list from driving
    unbounded work.
    """
    if depth > _MAX_JSON_DEPTH:
        raise _RouterError(400, "Request body is nested too deeply.")
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LEN:
            raise _RouterError(400, "A text value in the request body is too long.")
    elif isinstance(value, list):
        if len(value) > _MAX_LIST_LEN:
            raise _RouterError(400, "A list in the request body has too many items.")
        for item in value:
            _check_body_shape(item, depth + 1)
    elif isinstance(value, dict):
        if len(value) > _MAX_LIST_LEN:
            raise _RouterError(400, "An object in the request body has too many keys.")
        for key, item in value.items():
            _check_body_shape(key, depth + 1)
            _check_body_shape(item, depth + 1)


def _check_path_ids(params: dict[str, str]) -> None:
    """Reject malformed resource ids in the path (any param named ``*Id``).

    A malformed id cannot name a real resource, so it gets the same 404 as an
    unknown one; nothing reaches the repository.
    """
    for name, value in params.items():
        if name.endswith("Id") and not _ID_RE.match(value):
            raise _RouterError(404, "Not found.")


def _opt_str(value: Any, field: str) -> str | None:
    """Return ``value`` when it is a string or absent; otherwise raise a 400.

    Request fields the services treat as text must arrive as JSON strings; a
    number, list, object or boolean is a client error, not something to coerce.
    """
    if value is None or isinstance(value, str):
        return value
    raise _RouterError(400, f"'{field}' must be a string.", field=field)


def _query(event: dict[str, Any]) -> dict[str, str]:
    """Return the query-string parameters as a ``{str: str}`` dict (never None)."""
    params = event.get("queryStringParameters")
    if not isinstance(params, dict):
        return {}
    return {str(k): str(v) for k, v in params.items() if v is not None}


def _int_param(value: str | None, name: str, *, year_range: bool = True) -> int:
    """Parse an integer query/path value, raising a 400 :class:`_RouterError`.

    Used for ``taxYear`` and day-count query params so a bad value becomes a
    clean 400 rather than an unhandled 500.
    """
    if value is None or str(value).strip() == "":
        raise _RouterError(400, f"'{name}' is required.", field=name)
    text = str(value).strip()
    if not _INT_RE.match(text):
        raise _RouterError(400, f"'{name}' must be an integer.", field=name)
    number = int(text)
    if year_range and name == "taxYear" and not _MIN_TAX_YEAR <= number <= _MAX_TAX_YEAR:
        raise _RouterError(
            400,
            f"'{name}' must be between {_MIN_TAX_YEAR} and {_MAX_TAX_YEAR}.",
            field=name,
        )
    return number


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

    def __init__(
        self,
        repo: Any,
        files: Any,
        rentcast: Any,
        autocomplete: Any,
        textract: Any = None,
        package_invoker: Any = None,
    ) -> None:
        self.package_invoker = package_invoker
        self.repo = repo
        self.files = files
        self.rentcast = rentcast
        self.autocomplete = autocomplete
        self.textract = textract


_WIRING: _Wiring | None = None


def configure(
    *,
    repo: Any,
    files: Any = None,
    rentcast: Any = None,
    autocomplete: Any = None,
    textract: Any = None,
    package_invoker: Any = None,
) -> None:
    """Inject the router's wiring (repository + adapters), replacing any default.

    Tests call this with moto-backed collaborators so the handler runs entirely
    against in-memory AWS with no environment or credentials. Adapters not needed
    by the routes under test may be omitted (``None``); a route that needs a
    missing adapter surfaces a clean 503 rather than crashing. The ``textract``
    collaborator (a :class:`~logstead.adapters.textract.TextractAdapter` or a
    fake) powers the Schedule E PDF-extraction routes; omitting it makes those
    routes return 503 via :func:`_require_textract`.
    """
    global _WIRING
    _WIRING = _Wiring(
        repo=repo,
        files=files,
        rentcast=rentcast,
        autocomplete=autocomplete,
        textract=textract,
        package_invoker=package_invoker,
    )


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
    from logstead.adapters.textract import TextractAdapter
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
    # Textract powers Schedule E PDF extraction ("layer 2"). The boto3 client is
    # created lazily here (like the S3 client) so importing this module never
    # requires AWS credentials; the adapter is a thin wrapper the extraction
    # service composes. Async document analysis is resource-less, so no bucket
    # gate is needed — the client is always built when wiring from the env.
    textract_client = boto3.client("textract", region_name=region)
    textract = TextractAdapter(textract_client)
    # The package worker is invoked asynchronously; without its function name the
    # create route returns 503 and creates no job.
    package_invoker = None
    worker_function = _env("PACKAGE_WORKER_FUNCTION")
    if worker_function:
        from logstead.adapters.package_invoker import PackageInvoker

        package_invoker = PackageInvoker(
            boto3.client("lambda", region_name=region), worker_function
        )

    return _Wiring(
        repo=repo,
        files=files,
        rentcast=rentcast,
        autocomplete=autocomplete,
        textract=textract,
        package_invoker=package_invoker,
    )


def _wiring() -> _Wiring:
    """Return the container-scoped wiring, building it from env on first use."""
    global _WIRING
    if _WIRING is None:
        _WIRING = _build_wiring_from_env()
    return _WIRING


def get_wiring() -> _Wiring:
    """Public accessor for the container wiring (used by the package worker)."""
    return _wiring()


def to_jsonable(value: Any) -> Any:
    """Public alias of :func:`_to_jsonable` (used by the package worker)."""
    return _to_jsonable(value)


def _require_files(wiring: _Wiring) -> Any:
    """Return the S3 file adapter or raise a 503 when file storage is unconfigured."""
    if wiring.files is None:
        raise _RouterError(503, "File storage is not configured.")
    return wiring.files


def _require_textract(wiring: _Wiring) -> Any:
    """Return the Textract adapter or raise a 503 when it is unconfigured.

    Mirrors :func:`_require_files`: a Schedule E extraction route hit with no
    Textract adapter wired (e.g. a test ``configure(...)`` without ``textract``)
    surfaces a clean 503 rather than crashing.
    """
    if wiring.textract is None:
        raise _RouterError(503, "Document extraction is not configured.")
    return wiring.textract


# --- Service constructors (per request) --------------------------------------
#
# Services are constructed fresh per request from the shared wiring. They are
# thin, stateless wrappers around the repo/adapters (plus the resolved user for
# the property service), so per-request construction is cheap and keeps user
# scoping explicit.


def _property_service(wiring: _Wiring, user: Any) -> Any:
    from logstead.services.property import PropertyService

    return PropertyService(wiring.repo, user)


def _wire_business_and_property(
    wiring: _Wiring, user: Any, *, require_files: bool = False
) -> tuple[Any, Any]:
    """Construct the mutually-dependent Business/Property services for a request.

    ``BusinessService`` needs a ``PropertyService`` (for ``linked_properties``
    and the delete-guard) and ``PropertyService`` needs a ``BusinessService``
    (for ``set_business``'s ownership check). Neither touches the other at import
    time or in its constructor, so the cycle is resolved by constructing both and
    setting the collaborator reference after construction, exactly as the
    ``services/business.py`` module docstring prescribes::

        biz = BusinessService(repo, user, files=<files-or-None>)
        prop = PropertyService(repo, user, business_service=biz)
        biz._property_service = prop

    ``require_files`` controls the S3 adapter the business service receives: the
    document routes pass ``True`` so an unconfigured bucket surfaces a clean 503
    via :func:`_require_files`; every other route passes ``wiring.files`` (which
    may be ``None``) since only the document methods need S3 — ``linked_properties``
    and ``delete`` need only the wired ``prop`` collaborator.

    Returns the ``(business_service, property_service)`` pair, both fully wired.
    """
    from logstead.services.business import BusinessService
    from logstead.services.property import PropertyService

    files = _require_files(wiring) if require_files else wiring.files
    biz = BusinessService(wiring.repo, user, files=files)
    prop = PropertyService(wiring.repo, user, business_service=biz)
    biz._property_service = prop
    return biz, prop


def _business_service(wiring: _Wiring, user: Any, *, require_files: bool = False) -> Any:
    """Return a fully-wired :class:`BusinessService` for this request.

    Document routes pass ``require_files=True`` so an unconfigured S3 bucket
    yields a 503; all other business routes leave files optional. The returned
    service always has its ``PropertyService`` collaborator wired so
    ``linked_properties``/``delete`` work (see :func:`_wire_business_and_property`).
    """
    biz, _ = _wire_business_and_property(wiring, user, require_files=require_files)
    return biz


def _property_service_with_business(wiring: _Wiring, user: Any) -> Any:
    """Return a :class:`PropertyService` whose ``business_service`` is wired.

    Used by the ``PUT /properties/{propertyId}/business`` link route so
    ``set_business``'s ownership check (Req 9.5) can validate the target business
    against a real :class:`BusinessService`.
    """
    _, prop = _wire_business_and_property(wiring, user)
    return prop


def _transaction_service(wiring: _Wiring) -> Any:
    from logstead.services.transaction import TransactionService

    return TransactionService(wiring.repo, _require_files(wiring))


def _itemized_service(wiring: _Wiring) -> Any:
    from logstead.services.itemized import ItemizedExpenseService

    return ItemizedExpenseService(_transaction_service(wiring))


def _depreciation_service(wiring: _Wiring) -> Any:
    from logstead.services.depreciation import DepreciationService

    return DepreciationService(wiring.repo)


def _loan_service(wiring: _Wiring) -> Any:
    from logstead.services.loan import LoanService

    return LoanService(wiring.repo)


def _require_owned_property(wiring: _Wiring, user: Any, property_id: str) -> dict[str, Any] | None:
    """Return a 404 response unless the property exists and belongs to the user.

    A missing and a foreign property yield the identical ``Property not found.``
    response (Requirement 8.7). Returns ``None`` when the caller may proceed.
    """
    got = _property_service(wiring, user).get(property_id)
    return None if got.is_ok else _result_response(got)


def _property_scoped(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Guard a ``/properties/{propertyId}/...`` handler with an ownership check.

    Child items (photos, transactions, receipts, assets, ...) live under
    ``PROPERTY#<id>`` partitions that are keyed by property id alone, and their
    services take no user. The router therefore proves the property belongs to
    the authenticated user *before* the service runs. A missing property and
    another user's property return the identical 404, so existence never leaks
    and no child data is read or written.
    """

    @functools.wraps(fn)
    def guarded(wiring, user, params, body, query):  # type: ignore[no-untyped-def]
        denied = _require_owned_property(wiring, user, params["propertyId"])
        if denied is not None:
            return denied
        return fn(wiring, user, params, body, query)

    return guarded


# --- Activity history (best effort, router layer) ------------------------------
#
# Recording is attached around the mutation handlers and nowhere else: no domain
# service imports or receives the recorder (Requirements 19.1, 20.3). The
# wrapper reads the record before the mutation (best effort), runs the handler,
# and records only after a 200, 201 or 204. Every failure inside the wrapper is
# swallowed and logged, so the handler's response is returned unchanged
# (Requirement 20.2).


def _activity_recorder(wiring: _Wiring, user: Any) -> Any:
    from logstead.services.activity import ActivityRecorder
    from logstead.services.auth import user_id_of

    return ActivityRecorder(wiring.repo, user_id_of(user))


def _activity_service(wiring: _Wiring, user: Any, *, restore: bool = False) -> Any:
    """Build the :class:`ActivityService` for ``user``.

    Listing never creates records, so it does not need file storage; restore
    builds the same file-backed services the toast Undo create path uses.
    """
    from logstead.services.activity import ActivityService
    from logstead.services.auth import user_id_of

    if restore or wiring.files is not None:
        transactions: Any = _transaction_service(wiring)
        itemized: Any = _itemized_service(wiring)
    else:
        transactions = itemized = None
    return ActivityService(
        wiring.repo,
        user_id_of(user),
        transactions,
        itemized,
        _depreciation_service(wiring),
        _loan_service(wiring),
        _activity_recorder(wiring, user),
    )


@dataclass(frozen=True)
class _ActivitySpec:
    """How one mutation handler is recorded.

    ``before`` reads the record ahead of the mutation (``None`` result means
    "unknown", which only costs the event its before values). ``events`` turns
    the before value and the parsed success body into zero or more events.
    ``purge`` names an activity purge that runs, after success, ahead of the
    events (``"user"`` or ``"property"``).
    """

    events: Callable[..., list[Any]]
    before: Callable[..., Any] | None = None
    purge: str | None = None


def _with_activity(spec: _ActivitySpec) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    def decorate(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(fn)
        def wrapped(wiring, user, params, body, query):  # type: ignore[no-untyped-def]
            before: Any = None
            if spec.before is not None:
                try:
                    before = spec.before(wiring, user, params, body, query)
                except Exception as exc:  # noqa: BLE001 - best effort
                    _log.warning("activity before-read failed: %s", exc_summary(exc))
            response = fn(wiring, user, params, body, query)
            if response.get("statusCode") in (200, 201, 204):
                try:
                    _record_activity(spec, wiring, user, params, body, query, before, response)
                except Exception as exc:  # noqa: BLE001 - never fail the mutation
                    _log.warning("activity recording failed: %s", exc_summary(exc))
            return response

        return wrapped

    return decorate


def _record_activity(spec, wiring, user, params, body, query, before, response) -> None:  # type: ignore[no-untyped-def]
    raw = response.get("body")
    data = json.loads(raw) if isinstance(raw, str) and raw else None
    recorder = _activity_recorder(wiring, user)
    if spec.purge == "property":
        recorder.purge_property(params["propertyId"])
    elif spec.purge == "user":
        recorder.purge_user()
    for event in spec.events(wiring, user, params, body, query, before, data):
        recorder.record(event)


def _activity_property_name(wiring: _Wiring, user: Any, property_id: str | None) -> str | None:
    if not property_id:
        return None
    try:
        got = _property_service(wiring, user).get(property_id)
    except Exception:  # noqa: BLE001
        return None
    return got.value.name if got.is_ok else None


def _activity_receipts(wiring: _Wiring, property_id: str, txn: Any) -> int | None:
    """0 or 1 receipt rows; ``None`` when unknown (which makes a delete not restorable)."""
    try:
        return 1 if _transaction_service(wiring).has_receipt(property_id, txn) else 0
    except Exception:  # noqa: BLE001
        return None


def _restore_payload(entity: str, record: dict[str, Any]) -> dict[str, Any]:
    """Snake_case create payload the activity restore parses: the allow-listed
    fields, plus ``tax_year`` for an itemized entry and the optional create
    fields an asset or loan needs to come back equal."""
    from logstead.services import activity_events as ev

    payload: dict[str, Any] = dict(ev.project(entity, record))
    if entity == "itemized_entry":
        date = record.get("date")
        if isinstance(date, str) and date[:4].isdigit():
            payload["tax_year"] = int(date[:4])
    elif entity == "asset":
        overrides = record.get("depreciation_overrides")
        if overrides:
            payload["depreciation_overrides"] = dict(overrides)
    elif entity == "loan":
        for name in ("extra_principal", "payoff_date", "original_principal", "closing_date"):
            if record.get(name) is not None:
                payload[name] = record[name]
    return payload


def _crud_event(
    wiring: _Wiring,
    user: Any,
    action: str,
    entity: str,
    property_id: str | None,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    receipts: int | None = None,
    property_name: str | None = None,
) -> list[Any]:
    """One create, update or delete event, or no event for an unchanged update."""
    from logstead.services import activity_events as ev
    from logstead.services.activity import NewEvent

    record = after if action == "create" else before
    record_id = str(record["id"]) if record and record.get("id") is not None else None
    if action == "create":
        stored_before, stored_after = None, ev.project(entity, after or {})
        full_before, full_after = None, stored_after
    elif action == "delete":
        stored_before, stored_after = ev.project(entity, before or {}), None
        full_before, full_after = stored_before, None
    else:
        stored_before, stored_after = ev.diff(entity, before or {}, after or {})
        if not stored_before and not stored_after:
            return []
        full_before, full_after = ev.project(entity, before or {}), ev.project(entity, after or {})
    restorable = action == "delete" and ev.is_restorable(entity, action, before or {}, receipts)
    return [
        NewEvent(
            action=action,
            entity=entity,
            summary=ev.summarize(action, entity, full_before, full_after),
            record_id=record_id,
            property_id=property_id,
            property_name=property_name
            if property_name is not None
            else _activity_property_name(wiring, user, property_id),
            before=stored_before,
            after=stored_after,
            restorable=restorable,
            restore_payload=_restore_payload(entity, before or {}) if restorable else None,
        )
    ]


# Transactions and itemized entries (both are stored as transactions).


def _tx_entity(record: dict[str, Any] | None) -> str:
    return "itemized_entry" if record and record.get("itemized") else "transaction"


def _before_transaction(id_param: str, *, receipts: bool = False) -> Callable[..., Any]:
    def read(wiring, user, params, body, query):  # type: ignore[no-untyped-def]
        got = _transaction_service(wiring).get(params["propertyId"], params[id_param])
        if not got.is_ok:
            return None
        return {
            "record": _to_jsonable(got.value),
            "receipts": _activity_receipts(wiring, params["propertyId"], got.value)
            if receipts
            else None,
        }

    return read


def _tx_events(action: str) -> Callable[..., list[Any]]:
    def events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
        pid = params["propertyId"]
        if action == "create":
            return _crud_event(wiring, user, action, _tx_entity(data), pid, after=data)
        if not before:
            return []
        record = before["record"]
        return _crud_event(
            wiring,
            user,
            action,
            _tx_entity(record),
            pid,
            before=record,
            after=data if action == "update" else None,
            receipts=before["receipts"],
        )

    return events


# Itemized entered totals (recorded as `transaction` events).


def _before_total(year_from: str) -> Callable[..., Any]:
    def read(wiring, user, params, body, query):  # type: ignore[no-untyped-def]
        raw = body.get("tax_year", body.get("taxYear")) if year_from == "body" else query.get("taxYear")
        year = _int_param(None if raw is None else str(raw), "taxYear")
        got = _itemized_service(wiring).summary(params["propertyId"], params["categoryId"], year)
        if not got.is_ok:
            return None
        return [
            {
                "record": _to_jsonable(row),
                "receipts": _activity_receipts(wiring, params["propertyId"], row),
            }
            for row in got.value.entered_total_rows
        ]

    return read


def _set_total_events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
    after_rows = (data or {}).get("entered_total_rows") or []
    if before is None or len(before) > 1 or len(after_rows) != 1:
        return []
    pid = params["propertyId"]
    if not before:
        return _crud_event(wiring, user, "create", "transaction", pid, after=after_rows[0])
    return _crud_event(
        wiring, user, "update", "transaction", pid, before=before[0]["record"], after=after_rows[0]
    )


def _remove_total_events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
    if not before or len(before) != 1:
        return []
    return _crud_event(
        wiring,
        user,
        "delete",
        "transaction",
        params["propertyId"],
        before=before[0]["record"],
        receipts=before[0]["receipts"],
    )


# Assets, loans and properties.


def _before_asset(wiring, user, params, body, query):  # type: ignore[no-untyped-def]
    got = _depreciation_service(wiring).get_asset(params["propertyId"], params["assetId"])
    return _to_jsonable(got.value) if got.is_ok else None


def _before_loan(wiring, user, params, body, query):  # type: ignore[no-untyped-def]
    got = _loan_service(wiring).get_loan(params["propertyId"], params["loanId"])
    return _to_jsonable(got.value) if got.is_ok else None


def _before_property(wiring, user, params, body, query):  # type: ignore[no-untyped-def]
    got = _property_service(wiring, user).get(params["propertyId"])
    return _to_jsonable(got.value) if got.is_ok else None


def _record_events(entity: str, action: str) -> Callable[..., list[Any]]:
    """Events for an asset or loan create, update or delete."""

    def events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
        pid = params["propertyId"]
        if action == "create":
            return _crud_event(wiring, user, action, entity, pid, after=data)
        if before is None:
            return []
        return _crud_event(
            wiring, user, action, entity, pid, before=before,
            after=data if action == "update" else None,
        )

    return events


def _override_events(verb: str) -> Callable[..., list[Any]]:
    def events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
        from logstead.services import activity_events as ev
        from logstead.services.activity import NewEvent

        pid = params["propertyId"]
        name = (before or {}).get("description")
        summary = f"Updated loan: {name} (interest override {params['taxYear']} {verb})" if name else (
            f"Updated loan (interest override {params['taxYear']} {verb})"
        )
        return [
            NewEvent(
                action="update",
                entity="loan",
                summary=ev._clip(summary, 200),
                record_id=params["loanId"],
                property_id=pid,
                property_name=_activity_property_name(wiring, user, pid),
            )
        ]

    return events


def _property_events(action: str) -> Callable[..., list[Any]]:
    def events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
        if action == "create":
            record = data or {}
            return _crud_event(
                wiring, user, action, "property", record.get("id"), after=record,
                property_name=record.get("name"),
            )
        if before is None:
            return []
        return _crud_event(
            wiring, user, action, "property", params["propertyId"], before=before,
            after=data if action == "update" else None,
            property_name=(data or before).get("name") if action == "update" else before.get("name"),
        )

    return events


# Imports and backup.


def _import_event(entity: str, property_id: str | None, summary: str, counts: dict[str, int], wiring, user) -> list[Any]:  # type: ignore[no-untyped-def]
    from logstead.services.activity import NewEvent

    return [
        NewEvent(
            action="import",
            entity=entity,
            summary=summary,
            property_id=property_id,
            property_name=_activity_property_name(wiring, user, property_id),
            after={k: str(v) for k, v in counts.items() if v is not None},
        )
    ]


def _schedule_e_events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
    from logstead.services import activity_events as ev

    entries = (data or {}).get("entries") or []
    created = sum(len(e.get("created_transaction_ids") or []) for e in entries)
    replaced = sum(int(e.get("deleted_prior_count") or 0) for e in entries)
    pid = entries[0].get("property_id") if len(entries) == 1 else None
    counts = {"tax_year": (data or {}).get("tax_year"), "created": created, "replaced": replaced}
    return _import_event(
        "schedule_e", pid, ev.summarize("import", "schedule_e", None, None, counts), counts, wiring, user
    )


def _before_import_session(wiring, user, params, body, query):  # type: ignore[no-untyped-def]
    got = _import_service(wiring).get_session(params["sessionId"])
    return got.value.property_id if got.is_ok else None


def _expense_import_events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
    from logstead.services import activity_events as ev

    created = len((data or {}).get("created_ids") or [])
    if created == 0:
        return []
    session = (data or {}).get("session") or {}
    pid = session.get("property_id") or before
    return _import_event(
        "transaction", pid, ev.summarize("import", "transaction", None, None, {"created": created}),
        {"created": created}, wiring, user,
    )


def _backup_restore_events(wiring, user, params, body, query, before, data):  # type: ignore[no-untyped-def]
    from logstead.services import activity_events as ev

    counts = {k: v for k, v in (data or {}).items() if isinstance(v, int) and not isinstance(v, bool)}
    return _import_event(
        "backup", None, ev.summarize("import", "backup", None, None, counts), counts, wiring, user
    )


def _no_events(*_args: Any) -> list[Any]:
    return []


def _require_owned_session(
    wiring: _Wiring, user: Any, session_id: str
) -> dict[str, Any] | None:
    """Return a 404 response unless the import session belongs to the user.

    Import sessions live under ``IMPORT#<id>`` and carry no user id, so
    ownership is derived from the property they were created for. A missing
    session, and a session for a property the user does not own, yield the same
    404.
    """
    session = _import_service(wiring).get_session(session_id)
    if not session.is_ok:
        return _result_response(session)
    owned = _property_service(wiring, user).get(session.value.property_id)
    if owned.is_ok:
        return None
    return _result_response(
        Result.failure("not_found", "Import session not found.")
    )


def _photo_service(wiring: _Wiring) -> Any:
    from logstead.services.photo import PhotoService

    return PhotoService(wiring.repo, _require_files(wiring))


def _import_service(wiring: _Wiring) -> Any:
    from logstead.services.expense_import import ExpenseImportService

    # ``confirm`` creates real transactions; hand it the file-backed service
    # lazily so unconfigured storage only matters when a draft is converted.
    return ExpenseImportService(
        wiring.repo,
        transaction_creator=lambda data: _transaction_service(wiring).create(data),
    )


def _schedule_e_import_service(wiring: _Wiring, user: Any) -> Any:
    """Return a per-request Schedule E :class:`ImportService` for this user.

    Distinct from :func:`_import_service` (the PDF-expense feature's
    ``ExpenseImportService``), which is left untouched. ``ImportService`` is
    scoped to the authenticated user and composes a user-scoped
    ``PropertyService`` (built internally from ``repo`` + ``user``) and a
    ``TransactionService`` for synthesis. ``TransactionService`` needs the S3
    adapter only for receipts — which synthesis never creates — so the real
    adapter is required here exactly like :func:`_transaction_service`, keeping
    wiring consistent with the other transaction routes.
    """
    from logstead.services.schedule_e_import import ImportService

    return ImportService(wiring.repo, user, files=_require_files(wiring))


def _extraction_service(wiring: _Wiring, user: Any) -> Any:
    """Return a per-request Schedule E :class:`ExtractionService` ("layer 2").

    Distinct from both :func:`_import_service` (the PDF-expense feature's
    ``ExpenseImportService``) and :func:`_schedule_e_import_service` (layer-1
    confirm), which are left untouched (Req 13.2). ``ExtractionService`` is
    scoped to the authenticated user and composes the user-scoped repository,
    the S3 file adapter (presigned PUT / PDF-signature read / terminal-state
    delete, so an unconfigured bucket surfaces the standard 503 via
    :func:`_require_files`), and the Textract adapter (async start/get, 503 via
    :func:`_require_textract` when unconfigured).
    """
    from logstead.services.schedule_e_extraction import ExtractionService

    return ExtractionService(
        wiring.repo,
        user,
        files=_require_files(wiring),
        textract=_require_textract(wiring),
    )


def _reporting_service(wiring: _Wiring, user: Any) -> Any:
    from logstead.services.report import ReportingService

    return ReportingService(
        _transaction_service(wiring),
        _depreciation_service(wiring),
        _property_service(wiring, user),
        loans=_loan_service(wiring),
    )


def _enrichment_service(wiring: _Wiring) -> Any:
    from logstead.services.enrichment import AddressEnrichmentService

    if wiring.autocomplete is None or wiring.rentcast is None:
        raise _RouterError(503, "Address enrichment is not configured.")
    return AddressEnrichmentService(wiring.autocomplete, wiring.rentcast)


def _backup_service(wiring: _Wiring, user: Any) -> Any:
    from logstead.services.backup import BackupService

    # Backup clear/restore purge and rewrite S3 binaries, so the S3 adapter is
    # required: an unconfigured bucket surfaces the standard 503 here, just like
    # the photo/receipt routes (design "Route surface + wiring").
    return BackupService(wiring.repo, _require_files(wiring), user)


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
        name=_opt_str(body.get("name"), "name"),
        address_text=_opt_str(
            body.get("address_text", body.get("addressText")), "address_text"
        ),
        property_type=_opt_str(
            body.get("property_type", body.get("propertyType")), "property_type"
        ),
        details=details,
    )


def _business_input(body: dict[str, Any]) -> Any:
    """Map a JSON body to a :class:`BusinessInput` (accepts snake or camel case).

    Mirrors :func:`_property_input`'s dual-case tolerance so the frontend may
    send either naming convention. ``legal_name``/``entity_type`` are validated
    by the service; the remaining fields are optional and carried verbatim
    (``ein`` is stored byte-for-byte, Req 1.6).
    """
    from logstead.models.business import BusinessInput

    return BusinessInput(
        legal_name=_opt_str(
            body.get("legal_name", body.get("legalName")), "legal_name"
        ),
        entity_type=_opt_str(
            body.get("entity_type", body.get("entityType")), "entity_type"
        ),
        ein=_opt_str(body.get("ein"), "ein"),
        formation_state=_opt_str(
            body.get("formation_state", body.get("formationState")), "formation_state"
        ),
        formation_date=_opt_str(
            body.get("formation_date", body.get("formationDate")), "formation_date"
        ),
        business_address=_opt_str(
            body.get("business_address", body.get("businessAddress")),
            "business_address",
        ),
        tax_year_end=_opt_str(
            body.get("tax_year_end", body.get("taxYearEnd")), "tax_year_end"
        ),
        note=_opt_str(body.get("note"), "note"),
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    """Coerce a JSON amount (string or number) to ``Decimal``; ``None`` when absent.

    Money arrives as a string in requests (the SPA sends money as strings). A bad
    value raises a 400 :class:`_RouterError` so it never reaches the service as a
    surprise type.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (bool, list, dict)):
        raise _RouterError(400, "Amount is not a valid number.", field="amount")
    try:
        amount = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - any bad numeric literal is a 400
        raise _RouterError(400, "Amount is not a valid number.", field="amount") from exc
    if not amount.is_finite():
        raise _RouterError(400, "Amount is not a valid number.", field="amount")
    if abs(amount) > _MAX_ABS_AMOUNT:
        raise _RouterError(400, "Amount is too large.", field="amount")
    return amount


def _transaction_input(body: dict[str, Any], property_id: str) -> Any:
    """Map a JSON body + path property id to a :class:`TransactionInput`."""
    from logstead.models.transaction import TransactionInput

    return TransactionInput(
        property_id=property_id,
        date=_opt_str(body.get("date"), "date"),
        amount=_decimal_or_none(body.get("amount")),
        type=_opt_str(body.get("type"), "type"),
        category_id=_opt_str(
            body.get("category_id", body.get("categoryId")), "category_id"
        ),
        description=_opt_str(body.get("description"), "description"),
    )


def _entry_input(body: dict[str, Any], property_id: str) -> Any:
    """Map a JSON body to an itemized :class:`EntryInput`.

    ``itemized``, ``imported``, ``type`` and ``property_id`` in the body are
    ignored: the service fixes them. ``property_id`` is accepted only for symmetry
    with the other input mappers and is not used.
    """
    from logstead.services.itemized import EntryInput

    raw_year = body.get("tax_year", body.get("taxYear"))
    tax_year = None if raw_year is None else _int_param(str(raw_year), "taxYear")
    return EntryInput(
        date=_opt_str(body.get("date"), "date"),
        amount=_decimal_or_none(body.get("amount")),
        description=_opt_str(body.get("description"), "description"),
        notes=_opt_str(body.get("notes"), "notes"),
        tax_year=tax_year,
    )


def _schedule_e_submission(body: dict[str, Any]) -> Any:
    """Map a JSON body to an :class:`ImportSubmission` (snake or camel case).

    Mirrors :func:`_transaction_input`'s dual-case tolerance so the SPA may send
    either naming convention: ``tax_year``/``taxYear``; per entry
    ``property_id``/``propertyId`` **or** ``new_property``/``newProperty`` (parsed
    into a :class:`PropertyInput` via :func:`_property_input`); per line
    ``schedule_e_line``/``scheduleELine``, ``amount`` (kept as a string and run
    through the service's ``util/money`` boundary), and ``description``.

    No business rules here (design "Handler stays thin"): money strings pass
    through verbatim and all validation (tax-year range, non-negative amounts,
    property mapping, Line 18 rejection) is the service's job. A ``tax_year``
    that is not an integer becomes a clean 400 via :func:`_int_param`; a blank /
    absent one is left as ``None`` so the service reports the ``tax_year`` field.
    """
    from logstead.models.schedule_e_import import (
        ImportSubmission,
        LineAmountInput,
        PropertyEntryInput,
    )

    raw_year = body.get("tax_year", body.get("taxYear"))
    if raw_year is None or (isinstance(raw_year, str) and raw_year.strip() == ""):
        tax_year: int | None = None
    else:
        tax_year = _int_param(str(raw_year), "taxYear")

    raw_entries = body.get("entries")
    entries: list[Any] = []
    if isinstance(raw_entries, list):
        for raw_entry in raw_entries:
            entry_dict = raw_entry if isinstance(raw_entry, dict) else {}
            raw_new = entry_dict.get("new_property", entry_dict.get("newProperty"))
            new_property = (
                _property_input(raw_new) if isinstance(raw_new, dict) else None
            )
            raw_lines = entry_dict.get("lines")
            lines: list[Any] = []
            if isinstance(raw_lines, list):
                for raw_line in raw_lines:
                    line_dict = raw_line if isinstance(raw_line, dict) else {}
                    lines.append(
                        LineAmountInput(
                            schedule_e_line=line_dict.get(
                                "schedule_e_line", line_dict.get("scheduleELine")
                            ),
                            amount=line_dict.get("amount"),
                            description=line_dict.get("description"),
                        )
                    )
            entries.append(
                PropertyEntryInput(
                    property_id=entry_dict.get(
                        "property_id", entry_dict.get("propertyId")
                    ),
                    new_property=new_property,
                    lines=lines,
                )
            )

    return ImportSubmission(tax_year=tax_year, entries=entries)


def _asset_input(body: dict[str, Any], property_id: str) -> Any:
    """Map a JSON body + path property id to an :class:`AssetInput`."""
    from logstead.models.depreciation import AssetInput

    recovery = body.get("recovery_period_years", body.get("recoveryPeriodYears"))

    # Req 1.2/1.4/1.5: no new routes; map the optional per-year override map from
    # the body (snake_case or camelCase) into ``dict[int, Decimal]``. Values arrive
    # as money strings; skip empty-string entries so they read as "no override" for
    # that year. A non-dict body value is ignored defensively.
    raw_overrides = body.get(
        "depreciation_overrides", body.get("depreciationOverrides")
    )
    overrides: dict[int, Decimal] = {}
    if isinstance(raw_overrides, dict):
        for year, value in raw_overrides.items():
            amount = _decimal_or_none(value)
            if amount is None:
                continue
            overrides[
                _int_param(str(year), "depreciation_overrides year")
            ] = amount

    return AssetInput(
        property_id=property_id,
        description=_opt_str(body.get("description"), "description"),
        cost_basis=_decimal_or_none(body.get("cost_basis", body.get("costBasis"))),
        placed_in_service_date=_opt_str(
            body.get("placed_in_service_date", body.get("placedInServiceDate")),
            "placed_in_service_date",
        ),
        recovery_period_years=_decimal_or_none(recovery),
        depreciation_overrides=overrides or None,
    )


class _FieldError(Exception):
    """A request-body problem tied to one field (becomes a 400 validation error)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _loan_decimal(value: Any, field: str) -> Decimal | None:
    """Parse a loan decimal field from a JSON string (or int) without floats.

    Empty/``None`` is "absent". A JSON float or bool is rejected so a binary
    float never enters the money path (Requirement 8.6).
    """
    if value is None or value == "":
        return None
    if isinstance(value, (bool, float)):
        raise _FieldError(field, "must be sent as a decimal string")
    if isinstance(value, (list, dict)):
        raise _FieldError(field, "must be a valid decimal number")
    try:
        # Non-finite and out-of-range values are left to the loan service, which
        # reports every invalid field together (multi-field ``errors`` list).
        return Decimal(str(value).strip())
    except ArithmeticError:
        raise _FieldError(field, "must be a valid decimal number") from None


def _loan_pick(body: dict[str, Any], snake: str, camel: str) -> Any:
    return body.get(snake, body.get(camel))


def _loan_input(body: dict[str, Any], property_id: str) -> Result[Any]:
    """Map a JSON body + path property id to a validated-shape ``LoanInput``.

    Accepts snake_case and camelCase keys. Money and the rate must be JSON
    strings (floats are rejected). Removed legacy keys (``term_months``,
    ``first_payment_date``, ``payment_override``) are ignored. The body carries
    no interest overrides. A field-specific parsing problem is returned as a
    ``validation`` failure.
    """
    from logstead.models.loan import LoanInput

    try:
        include = _loan_pick(body, "include_in_report", "includeInReport")
        if include is not None and not isinstance(include, bool):
            raise _FieldError("include_in_report", "must be true or false")
        return Result.success(
            LoanInput(
                property_id=property_id,
                description=_opt_str(body.get("description"), "description"),
                annual_interest_rate=_loan_decimal(
                    _loan_pick(body, "annual_interest_rate", "annualInterestRate"),
                    "annual_interest_rate",
                ),
                monthly_payment=_loan_decimal(
                    _loan_pick(body, "monthly_payment", "monthlyPayment"),
                    "monthly_payment",
                ),
                anchor_balance=_loan_decimal(
                    _loan_pick(body, "anchor_balance", "anchorBalance"),
                    "anchor_balance",
                ),
                anchor_date=_opt_str(_loan_pick(body, "anchor_date", "anchorDate"), "anchor_date") or None,
                original_principal=_loan_decimal(
                    _loan_pick(body, "original_principal", "originalPrincipal"),
                    "original_principal",
                ),
                extra_principal=_loan_decimal(
                    _loan_pick(body, "extra_principal", "extraPrincipal"),
                    "extra_principal",
                ),
                closing_date=_opt_str(_loan_pick(body, "closing_date", "closingDate"), "closing_date") or None,
                payoff_date=_opt_str(_loan_pick(body, "payoff_date", "payoffDate"), "payoff_date") or None,
                include_in_report=True if include is None else include,
            )
        )
    except _RouterError as exc:
        return Result.failure("validation", exc.message, field=exc.field)
    except _FieldError as exc:
        return Result.failure("validation", exc.message, field=exc.field)


# --- Route handlers ----------------------------------------------------------
#
# Each handler receives the resolved wiring, the authenticated user (or None for
# the public categories route), the captured path params, the parsed body, and
# the query dict. It calls exactly one service method and returns an HTTP proxy
# response. No handler contains business rules.


_CATEGORIES_CACHE_CONTROL = "private, max-age=3600"


def _list_categories(wiring: _Wiring, user: Any, params, body, query) -> dict[str, Any]:
    from logstead.services.category import list_categories

    response = _response(200, list_categories(wiring.repo))
    # Static catalog: let the browser reuse it. `private` because the route is
    # authenticated and must not be stored by shared caches.
    response["headers"]["Cache-Control"] = _CATEGORIES_CACHE_CONTROL
    return response


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

@_with_activity(_ActivitySpec(_property_events("create")))
def _create_property(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _result_response(service.create(_property_input(body)), success_status=201)


def _list_properties(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _response(200, service.list())


def _get_property(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _result_response(service.get(params["propertyId"]))


@_with_activity(_ActivitySpec(_property_events("update"), before=_before_property))
def _update_property(wiring, user, params, body, query) -> dict[str, Any]:
    service = _property_service(wiring, user)
    return _result_response(service.update(params["propertyId"], _property_input(body)))


@_with_activity(_ActivitySpec(_property_events("delete"), before=_before_property, purge="property"))
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
    raw_text = body.get("text")
    if raw_text is not None and not isinstance(raw_text, str):
        raise _RouterError(400, "'text' must be a string.", field="text")
    text = raw_text or ""
    result = service.set_note(params["propertyId"], text)
    if not result.is_ok:
        return _result_response(result)
    return _response(200, {"text": result.value})


# -- Property photos --

@_property_scoped
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


@_property_scoped
def _list_photos(wiring, user, params, body, query) -> dict[str, Any]:
    service = _photo_service(wiring)
    return _result_response(service.list_photos(params["propertyId"]))


@_property_scoped
def _delete_photo(wiring, user, params, body, query) -> dict[str, Any]:
    service = _photo_service(wiring)
    return _result_response(service.delete_photo(params["propertyId"], params["photoId"]))


@_property_scoped
def _set_photo_cover(wiring, user, params, body, query) -> dict[str, Any]:
    service = _photo_service(wiring)
    return _result_response(
        service.set_cover(params["propertyId"], params["photoId"])
    )


# -- Transactions --

@_property_scoped
@_with_activity(_ActivitySpec(_tx_events("create")))
def _create_transaction(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.create(_transaction_input(body, params["propertyId"])),
        success_status=201,
    )


@_property_scoped
def _list_transactions(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    tax_year = _int_param(query.get("taxYear"), "taxYear") if query.get("taxYear") else None
    return _result_response(service.list_for_property(params["propertyId"], tax_year))


@_property_scoped
def _get_transaction(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.get(params["propertyId"], params["transactionId"])
    )


@_property_scoped
@_with_activity(_ActivitySpec(_tx_events("update"), before=_before_transaction("transactionId")))
def _update_transaction(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.update(
            params["propertyId"],
            params["transactionId"],
            _transaction_input(body, params["propertyId"]),
        )
    )


@_property_scoped
@_with_activity(_ActivitySpec(_tx_events("delete"), before=_before_transaction("transactionId", receipts=True)))
def _delete_transaction(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.delete(params["propertyId"], params["transactionId"])
    )


# -- Itemized expenses --

@_property_scoped
def _itemized_summary(wiring, user, params, body, query) -> dict[str, Any]:
    tax_year = _int_param(query.get("taxYear"), "taxYear")
    return _result_response(
        _itemized_service(wiring).summary(
            params["propertyId"], params["categoryId"], tax_year
        )
    )


@_property_scoped
@_with_activity(_ActivitySpec(_tx_events("create")))
def _create_itemized_entry(wiring, user, params, body, query) -> dict[str, Any]:
    return _result_response(
        _itemized_service(wiring).create_entry(
            params["propertyId"],
            params["categoryId"],
            _entry_input(body, params["propertyId"]),
        ),
        success_status=201,
    )


@_property_scoped
@_with_activity(_ActivitySpec(_tx_events("update"), before=_before_transaction("entryId")))
def _update_itemized_entry(wiring, user, params, body, query) -> dict[str, Any]:
    return _result_response(
        _itemized_service(wiring).update_entry(
            params["propertyId"],
            params["categoryId"],
            params["entryId"],
            _entry_input(body, params["propertyId"]),
        )
    )


@_property_scoped
@_with_activity(_ActivitySpec(_tx_events("delete"), before=_before_transaction("entryId", receipts=True)))
def _delete_itemized_entry(wiring, user, params, body, query) -> dict[str, Any]:
    return _result_response(
        _itemized_service(wiring).delete_entry(
            params["propertyId"], params["categoryId"], params["entryId"]
        )
    )


@_property_scoped
@_with_activity(_ActivitySpec(_set_total_events, before=_before_total("body")))
def _set_itemized_total(wiring, user, params, body, query) -> dict[str, Any]:
    tax_year = _int_param(str(body.get("tax_year", body.get("taxYear"))), "taxYear")
    return _result_response(
        _itemized_service(wiring).set_total(
            params["propertyId"],
            params["categoryId"],
            tax_year,
            _decimal_or_none(body.get("amount")),
        )
    )


@_property_scoped
@_with_activity(_ActivitySpec(_remove_total_events, before=_before_total("query")))
def _remove_itemized_total(wiring, user, params, body, query) -> dict[str, Any]:
    tax_year = _int_param(query.get("taxYear"), "taxYear")
    return _result_response(
        _itemized_service(wiring).remove_total(
            params["propertyId"], params["categoryId"], tax_year
        )
    )


@_property_scoped
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


@_property_scoped
def _list_receipts(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.list_receipts(params["propertyId"], params["transactionId"])
    )


@_property_scoped
def _delete_receipt(wiring, user, params, body, query) -> dict[str, Any]:
    service = _transaction_service(wiring)
    return _result_response(
        service.delete_receipt(
            params["propertyId"], params["transactionId"], params["documentId"]
        )
    )


# -- Depreciable assets --

@_property_scoped
@_with_activity(_ActivitySpec(_record_events("asset", "create")))
def _create_asset(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _result_response(
        service.create_asset(_asset_input(body, params["propertyId"])),
        success_status=201,
    )


@_property_scoped
def _list_assets(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _response(200, service.list_assets(params["propertyId"]))


@_property_scoped
def _get_asset(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _result_response(service.get_asset(params["propertyId"], params["assetId"]))


@_property_scoped
@_with_activity(_ActivitySpec(_record_events("asset", "update"), before=_before_asset))
def _update_asset(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _result_response(
        service.update_asset(
            params["propertyId"], params["assetId"], _asset_input(body, params["propertyId"])
        )
    )


@_property_scoped
@_with_activity(_ActivitySpec(_record_events("asset", "delete"), before=_before_asset))
def _delete_asset(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _result_response(
        service.delete_asset(params["propertyId"], params["assetId"])
    )


@_property_scoped
def _asset_schedule(wiring, user, params, body, query) -> dict[str, Any]:
    service = _depreciation_service(wiring)
    return _response(
        200, service.schedule_for(params["propertyId"], params["assetId"])
    )


# -- Loans --
# Every handler checks property ownership first (Requirements 1.11, 8.7); a
# missing and a foreign property yield the identical 404.


@_property_scoped
@_with_activity(_ActivitySpec(_record_events("loan", "create")))
def _create_loan(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    parsed = _loan_input(body, params["propertyId"])
    if not parsed.is_ok:
        return _result_response(parsed)
    return _result_response(
        _loan_service(wiring).create_loan(parsed.value), success_status=201
    )


def _list_loans(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    return _result_response(_loan_service(wiring).list_loans(params["propertyId"]))


def _loan_line12_impact(wiring, user, params, body, query) -> dict[str, Any]:
    """Years where included-loan interest supersedes manual Line 12 entries."""
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    return _result_response(
        _reporting_service(wiring, user).line12_impact(params["propertyId"])
    )


def _get_loan(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    return _result_response(
        _loan_service(wiring).get_loan(params["propertyId"], params["loanId"])
    )


@_property_scoped
@_with_activity(_ActivitySpec(_record_events("loan", "update"), before=_before_loan))
def _update_loan(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    parsed = _loan_input(body, params["propertyId"])
    if not parsed.is_ok:
        return _result_response(parsed)
    return _result_response(
        _loan_service(wiring).update_loan(
            params["propertyId"], params["loanId"], parsed.value
        )
    )


@_property_scoped
@_with_activity(_ActivitySpec(_record_events("loan", "delete"), before=_before_loan))
def _delete_loan(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    return _result_response(
        _loan_service(wiring).delete_loan(params["propertyId"], params["loanId"])
    )


def _loan_schedule(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    return _result_response(
        _loan_service(wiring).schedule_for(params["propertyId"], params["loanId"])
    )


@_property_scoped
@_with_activity(_ActivitySpec(_override_events("set"), before=_before_loan))
def _set_interest_override(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    # The loan service owns the override-year range (and names the field).
    tax_year = _int_param(params["taxYear"], "taxYear", year_range=False)
    try:
        amount = _loan_decimal(body.get("interest"), "interest")
    except _FieldError as exc:
        return _result_response(
            Result.failure("validation", exc.message, field=exc.field)
        )
    if amount is None:
        return _result_response(
            Result.failure("validation", "interest is required.", field="interest")
        )
    return _result_response(
        _loan_service(wiring).set_interest_override(
            params["propertyId"], params["loanId"], tax_year, amount
        )
    )


@_property_scoped
@_with_activity(_ActivitySpec(_override_events("removed"), before=_before_loan))
def _clear_interest_override(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_property(wiring, user, params["propertyId"])
    if denied is not None:
        return denied
    tax_year = _int_param(params["taxYear"], "taxYear", year_range=False)
    return _result_response(
        _loan_service(wiring).clear_interest_override(
            params["propertyId"], params["loanId"], tax_year
        )
    )


def _earliest_year(wiring, user, params, body, query) -> dict[str, Any]:
    """Earliest calendar year with data for a property (ownership-checked)."""
    from logstead.services.dashboard import earliest_data_year

    got = _property_service(wiring, user).get(params["propertyId"])
    if not got.is_ok:
        return _result_response(got)
    year = earliest_data_year(
        params["propertyId"],
        _transaction_service(wiring),
        _depreciation_service(wiring),
    )
    return _response(200, {"earliest_year": year})


# -- Expense imports --

def _create_import(wiring, user, params, body, query) -> dict[str, Any]:
    service = _import_service(wiring)
    property_id = str(body.get("property_id", body.get("propertyId", "")))
    denied = _require_owned_property(wiring, user, property_id)
    if denied is not None:
        return denied
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
            content_type=_opt_str(
                body.get("content_type", body.get("contentType")), "content_type"
            ),
        ),
        success_status=201,
    )


def _get_import(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_session(wiring, user, params["sessionId"])
    if denied is not None:
        return denied
    service = _import_service(wiring)
    return _result_response(service.get_session(params["sessionId"]))


def _list_drafts(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_session(wiring, user, params["sessionId"])
    if denied is not None:
        return denied
    service = _import_service(wiring)
    return _response(200, service.list_drafts(params["sessionId"]))


def _update_draft(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_session(wiring, user, params["sessionId"])
    if denied is not None:
        return denied
    service = _import_service(wiring)
    return _result_response(
        service.update_draft(params["sessionId"], params["draftId"], body)
    )


def _remove_draft(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_session(wiring, user, params["sessionId"])
    if denied is not None:
        return denied
    service = _import_service(wiring)
    return _result_response(
        service.remove_draft(params["sessionId"], params["draftId"])
    )


@_with_activity(_ActivitySpec(_expense_import_events, before=_before_import_session))
def _confirm_import(wiring, user, params, body, query) -> dict[str, Any]:
    denied = _require_owned_session(wiring, user, params["sessionId"])
    if denied is not None:
        return denied
    service = _import_service(wiring)
    return _result_response(service.confirm(params["sessionId"]))


# -- Schedule E imports (distinct from the PDF-expense /imports feature) --

@_with_activity(_ActivitySpec(_schedule_e_events))
def _import_schedule_e(wiring, user, params, body, query) -> dict[str, Any]:
    """POST /imports/schedule-e: synthesize the imported set per property entry.

    Thin: parse the body into an :class:`ImportSubmission`, wire a user-scoped
    ``ImportService``, call ``import_schedule_e``, and map the ``Result`` to HTTP
    (``201`` on success; ``validation→400`` with the structured dotted ``field``;
    ``not_found→404``). No business rules.
    """
    service = _schedule_e_import_service(wiring, user)
    return _result_response(
        service.import_schedule_e(_schedule_e_submission(body)),
        success_status=201,
    )


def _remove_schedule_e_import(wiring, user, params, body, query) -> dict[str, Any]:
    """DELETE /imports/schedule-e/{propertyId}/{taxYear}: undo one imported set.

    The ``{taxYear}`` path segment is parsed with :func:`_int_param` so a
    non-integer value is a clean ``400`` before the service is called. Maps the
    ``Result`` to HTTP (``200`` on success; ``not_found→404``).
    """
    service = _schedule_e_import_service(wiring, user)
    tax_year = _int_param(params.get("taxYear"), "taxYear")
    return _result_response(
        service.remove_imported_set(params["propertyId"], tax_year)
    )


# -- Schedule E PDF extraction ("layer 2": extraction proposes, layer 1 persists) --

def _start_extraction(wiring, user, params, body, query) -> dict[str, Any]:
    """POST /imports/schedule-e/extractions: mint a job + issue a presigned PUT.

    Thin: parse ``filename``/``content_type`` from the body (dual snake/camel
    tolerance like the other upload routes), wire a user-scoped
    ``ExtractionService``, call ``start_extraction``, and map the ``Result`` to
    HTTP (``201`` on success with ``{job_id, upload_url}``; a non-PDF content
    type → ``validation``/``400`` identifying ``file``). No business rules.
    """
    service = _extraction_service(wiring, user)
    return _result_response(
        service.start_extraction(
            str(body.get("filename", "")),
            str(body.get("content_type", body.get("contentType", ""))),
        ),
        success_status=201,
    )


def _begin_extraction(wiring, user, params, body, query) -> dict[str, Any]:
    """POST /imports/schedule-e/extractions/{jobId}/start: kick off Textract.

    Thin: the ``{jobId}`` path param drives ``begin_extraction``; map the
    ``Result`` to HTTP (``200`` on success). A job missing / owned by another
    user → ``not_found``/``404``; an object that never landed → ``404`` (Textract
    is never called). A present-but-not-a-PDF object is a successful ``200`` poll
    whose body carries the ``failed`` outcome. No business rules.
    """
    service = _extraction_service(wiring, user)
    return _result_response(service.begin_extraction(params["jobId"]))


def _get_extraction(wiring, user, params, body, query) -> dict[str, Any]:
    """GET /imports/schedule-e/extractions/{jobId}: poll the job status.

    Thin: the ``{jobId}`` path param drives ``get_status``; map the ``Result`` to
    HTTP (``200``). A ``failed`` / ``no_schedule_e_found`` poll is itself a
    successful ``200`` whose body carries the negative outcome — the job ran. A
    job missing / owned by another user → ``not_found``/``404``. No business rules.
    """
    service = _extraction_service(wiring, user)
    return _result_response(service.get_status(params["jobId"]))


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
    if property_ids is not None:
        if len(property_ids) > 100 or not all(_ID_RE.match(p) for p in property_ids):
            raise _RouterError(
                400, "'propertyIds' is not a valid id list.", field="propertyIds"
            )
    return _result_response(service.combined_report(property_ids, tax_year))


def _parse_property_ids(query: dict[str, Any]) -> list[str] | None:
    """Parse the optional ``propertyIds`` query value (shared by report routes)."""
    ids_param = query.get("propertyIds")
    property_ids = [p for p in ids_param.split(",") if p] if ids_param else None
    if property_ids is not None:
        if len(property_ids) > 100 or not all(_ID_RE.match(p) for p in property_ids):
            raise _RouterError(
                400, "'propertyIds' is not a valid id list.", field="propertyIds"
            )
    return property_ids


class PackageServices(NamedTuple):
    """Per-user services the package builder and the PDF routes compose."""

    reports: Any
    itemized: Any
    transactions: Any
    properties: Any


def build_package_service(wiring: _Wiring, user_id: Any) -> PackageServices:
    """Wire the report-side services for ``user_id`` exactly as the report routes do.

    ``user_id`` is the user id string (or a ``UserContext``). Raises a 503
    :class:`_RouterError` when file storage is not configured.
    """
    return PackageServices(
        reports=_reporting_service(wiring, user_id),
        itemized=_itemized_service(wiring),
        transactions=_transaction_service(wiring),
        properties=_property_service(wiring, user_id),
    )


def _repairs_detail(itemized: Any, property_id: str, tax_year: int) -> Any:
    """Copy ``ItemizedExpenseService.summary`` for Repairs into a ``RepairsDetail``.

    Returns the failed ``Result`` when the summary fails, else the detail.
    """
    from logstead.services.report_pdf import RepairsDetail, RepairsEntry

    summary = itemized.summary(property_id, "repairs", tax_year)
    if not summary.is_ok:
        return summary
    s = summary.value
    return RepairsDetail(
        entries=tuple(
            RepairsEntry(id=e.id, date=e.date, description=e.description, amount=e.amount)
            for e in s.entries
        ),
        entered_total=s.entered_total,
        itemized_sum=s.itemized_sum,
        line_total=s.line_total,
        line_source=s.line_source,
    )


def _store_pdf(
    wiring: _Wiring, user: Any, content: bytes, filename: str
) -> dict[str, Any]:
    """Write the PDF under ``exports/pdf/<userId>/<random id>/`` and return the link body."""
    import uuid

    from logstead.adapters.s3_files import pdf_key
    from logstead.services.package_config import DOWNLOAD_LINK_SECONDS

    files = _require_files(wiring)
    key = pdf_key(user.user_id, uuid.uuid4().hex, filename)
    files.put_object(key, content, "application/pdf")
    url = files.presigned_get_url(
        key, expires_in=DOWNLOAD_LINK_SECONDS, download_filename=filename
    )
    return _response(
        200,
        {
            "download_url": url,
            "filename": filename,
            "content_type": "application/pdf",
            "size_bytes": len(content),
            "expires_in_seconds": DOWNLOAD_LINK_SECONDS,
        },
    )


def _today() -> Any:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date()


@_property_scoped
def _property_report_pdf(wiring, user, params, body, query) -> dict[str, Any]:
    from logstead.services.package_paths import slugify
    from logstead.services.report_pdf import render_property_pdf

    _require_files(wiring)
    tax_year = _int_param(query.get("taxYear"), "taxYear")
    property_id = params["propertyId"]
    services = build_package_service(wiring, user)
    report = services.reports.report_for(property_id, tax_year)
    if not report.is_ok:
        return _result_response(report)
    repairs = _repairs_detail(services.itemized, property_id, tax_year)
    if isinstance(repairs, Result):
        return _result_response(repairs)
    content = render_property_pdf(report.value, repairs, _today())
    slug = slugify(report.value.header.property_name, "property")
    return _store_pdf(wiring, user, content, f"schedule-e-{slug}-{tax_year}.pdf")


def _combined_report_pdf(wiring, user, params, body, query) -> dict[str, Any]:
    from logstead.services.report_pdf import render_combined_pdf

    _require_files(wiring)
    tax_year = _int_param(query.get("taxYear"), "taxYear")
    property_ids = _parse_property_ids(query)
    services = build_package_service(wiring, user)
    combined = services.reports.combined_report(property_ids, tax_year)
    if not combined.is_ok:
        return _result_response(combined)
    if not combined.value.properties:
        raise _RouterError(
            400, "No properties to include in the report.", field="propertyIds"
        )
    repairs: dict[str, Any] = {}
    for column in combined.value.properties:
        pid = column.header.property_id
        detail = _repairs_detail(services.itemized, pid, tax_year)
        if isinstance(detail, Result):
            return _result_response(detail)
        repairs[pid] = detail
    content = render_combined_pdf(combined.value, repairs, _today())
    return _store_pdf(wiring, user, content, f"schedule-e-combined-{tax_year}.pdf")


# -- Accountant package jobs --


def _package_job_service(wiring: _Wiring, user: Any, *, need_invoker: bool) -> Any:
    """Build the per-request :class:`PackageJobService`; 503 when not configured."""
    from logstead.services.package_jobs import PackageJobService

    files = _require_files(wiring)
    if need_invoker and wiring.package_invoker is None:
        raise _RouterError(503, "Accountant packages are not available.")
    return PackageJobService(wiring.repo, user, files, wiring.package_invoker)


def _package_body_year(body: dict[str, Any]) -> int:
    key = "taxYear" if "taxYear" in body and "tax_year" not in body else "tax_year"
    raw = body.get(key)
    try:
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise _RouterError(400, f"'{key}' must be an integer.", field=key)
        return _int_param(str(raw), "taxYear")
    except _RouterError as exc:
        raise _RouterError(400, exc.message.replace("taxYear", key), field=key) from None


def _package_body_property_ids(body: dict[str, Any]) -> list[str] | None:
    key = "propertyIds" if "propertyIds" in body and "property_ids" not in body else "property_ids"
    raw = body.get(key)
    if raw is None:
        return None
    if (
        not isinstance(raw, list)
        or len(raw) > 100
        or not all(isinstance(p, str) and _ID_RE.match(p) for p in raw)
    ):
        raise _RouterError(400, f"'{key}' is not a valid id list.", field=key)
    return raw


def _create_package(wiring, user, params, body, query) -> dict[str, Any]:
    tax_year = _package_body_year(body)
    property_ids = _package_body_property_ids(body)
    service = _package_job_service(wiring, user, need_invoker=True)
    return _result_response(service.create(tax_year, property_ids), success_status=202)


def _list_packages(wiring, user, params, body, query) -> dict[str, Any]:
    service = _package_job_service(wiring, user, need_invoker=False)
    result = service.list()
    if not result.is_ok:
        return _result_response(result)
    return _response(200, {"jobs": result.value})


def _get_package(wiring, user, params, body, query) -> dict[str, Any]:
    service = _package_job_service(wiring, user, need_invoker=False)
    return _result_response(service.get(params["jobId"]))


def _delete_package(wiring, user, params, body, query) -> dict[str, Any]:
    service = _package_job_service(wiring, user, need_invoker=False)
    result = service.delete(params["jobId"])
    if not result.is_ok:
        return _result_response(result)
    return _response(200, {})


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
    # so the dashboard matches the report exactly), plus the depreciation
    # service used by the asset-summary endpoint for each property's asset count
    # and its authoritative per-year depreciation total (same figure as Line 18).
    return DashboardService(
        _property_service(wiring, user),
        _reporting_service(wiring, user),
        _depreciation_service(wiring),
        _transaction_service(wiring),
        loans=_loan_service(wiring),
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


def _dashboard_asset_summary(wiring, user, params, body, query) -> dict[str, Any]:
    # Read-only per-property depreciable-assets summary (Requirements 3.1, 3.2,
    # 3.4, 3.5). taxYear is optional; when absent the service defaults to the
    # current tax year, matching the other dashboard summaries.
    service = _dashboard_service_or_503(wiring, user)
    tax_year = _int_param(query.get("taxYear"), "taxYear") if query.get("taxYear") else None
    return _response(200, service.asset_summary(tax_year))


def _dashboard_trends(wiring, user, params, body, query) -> dict[str, Any]:
    # Portfolio-level year-over-year trends across every Data_Year (Requirements
    # 6, 7). Unlike the other dashboard summaries this takes no taxYear param:
    # the trends view is inherently multi-year, and _to_jsonable renders every
    # Money/Decimal as a two-decimal string just like the other endpoints.
    service = _dashboard_service_or_503(wiring, user)
    return _response(200, service.trends_summary())


# -- Carryforward (guarded: the service is written concurrently) --

def _carryforward_service_or_503(wiring: _Wiring, user: Any) -> Any:
    """Construct the Carryforward service, or raise 503 if it is not available.

    Mirrors :func:`_dashboard_service_or_503`: import the service lazily so this
    router imports cleanly whether or not the service has landed, and surface a
    clean 503 when a carryforward route is hit before the service is importable.
    """
    try:
        from logstead.services.carryforward import CarryforwardService  # type: ignore
    except ImportError as exc:
        raise _RouterError(503, "Carryforward is not available yet.") from exc
    # CarryforwardService re-derives each Data_Year's Schedule E net from the
    # reporting service across the user's properties, so it composes the same
    # reporting + property services the dashboard uses. The transaction and
    # depreciation services back the shared Data_Year derivation; the
    # transaction service needs the S3 adapter, so (like the trends path) an
    # unconfigured bucket surfaces the standard 503 via _require_files.
    return CarryforwardService(
        wiring.repo,
        user,
        _reporting_service(wiring, user),
        _property_service(wiring, user),
        _transaction_service(wiring),
        _depreciation_service(wiring),
        loans=_loan_service(wiring),
    )


# -- Global search (read-only) --
def _search_service(wiring: _Wiring, user: Any) -> Any:
    """Build the read-only :class:`SearchService` for ``user``."""
    from logstead.services.search import SearchService

    biz, prop = _wire_business_and_property(wiring, user)
    return SearchService(
        prop,
        _transaction_service(wiring),
        _depreciation_service(wiring),
        _loan_service(wiring),
        biz,
    )


def _search(wiring, user, params, body, query) -> dict[str, Any]:
    # GET /search?q=&limit=&propertyId=. Not @_property_scoped (no path id).
    # A malformed, missing or foreign propertyId all return the identical
    # "Property not found." 404 before anything is read. The query text is
    # never logged.
    q = query.get("q")
    if q is None:
        raise _RouterError(400, "'q' is required.", field="q")
    limit: int | None = None
    raw_limit = query.get("limit")
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            raise _RouterError(400, "limit must be an integer.", field="limit")
        limit = int(raw_limit)
    property_id = query.get("propertyId")
    if property_id is not None:
        if not _ID_RE.match(property_id):
            return _result_response(
                Result.failure("not_found", "Property not found.")
            )
        denied = _require_owned_property(wiring, user, property_id)
        if denied is not None:
            return denied
    result = _search_service(wiring, user).search(
        q, limit=limit, property_id=property_id
    )
    if result.is_ok:
        found = result.value
        _log.info(
            "search completed: groups=%d hits=%d scanned=%d truncated=%s",
            len(found.groups),
            sum(len(g.hits) for g in found.groups),
            found.scanned,
            found.truncated,
        )
    return _result_response(result)


# -- Activity history --


def _activity_list_args(query: dict[str, Any]) -> dict[str, Any]:
    """Parse the shared list parameters; the service validates ranges and kinds."""
    limit: int | None = None
    raw_limit = query.get("limit")
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            raise _RouterError(400, "limit must be an integer.", field="limit")
        limit = int(raw_limit)
    return {
        "limit": limit,
        "cursor": query.get("cursor"),
        "entity": query.get("entity"),
        "action": query.get("action"),
    }


def _activity_page_response(result: Result[Any]) -> dict[str, Any]:
    if not result.is_ok:
        return _result_response(result)
    page = result.value
    events = []
    for event in page.events:
        wire = _to_jsonable(event)
        wire["id"] = wire.pop("event_id")
        events.append(wire)
    return _response(200, {"events": events, "next_cursor": page.next_cursor})


def _list_activity(wiring, user, params, body, query) -> dict[str, Any]:
    # GET /activity?limit=&cursor=&entity=&action=&propertyId=. A malformed,
    # missing or foreign propertyId returns the identical "Property not found." 404.
    args = _activity_list_args(query)
    property_id = query.get("propertyId")
    if property_id is not None and not _ID_RE.match(property_id):
        return _result_response(Result.failure("not_found", "Property not found."))
    return _activity_page_response(
        _activity_service(wiring, user).list_user(property_id=property_id, **args)
    )


@_property_scoped
def _list_property_activity(wiring, user, params, body, query) -> dict[str, Any]:
    args = _activity_list_args(query)
    return _activity_page_response(
        _activity_service(wiring, user).list_property(params["propertyId"], **args)
    )


@_property_scoped
def _restore_activity(wiring, user, params, body, query) -> dict[str, Any]:
    return _result_response(
        _activity_service(wiring, user, restore=True).restore(
            params["propertyId"], params["eventId"]
        )
    )


# -- Year-end checklist (read-only) --

def _checklist_service(wiring: _Wiring, user: Any) -> Any:
    """Build the read-only :class:`ChecklistService` for ``user``.

    Uses the same collaborators as the report and carryforward routes.
    """
    from logstead.services.checklist import ChecklistService

    return ChecklistService(
        _reporting_service(wiring, user),
        _transaction_service(wiring),
        _depreciation_service(wiring),
        _loan_service(wiring),
        _property_service(wiring, user),
        _carryforward_service_or_503(wiring, user),
    )


# Public alias used by ``logstead.services.checklist.provider_for``.
build_checklist_service = _checklist_service


def _year_param(query: dict[str, Any]) -> int | None:
    """Return the validated ``taxYear`` query value, or ``None`` when absent."""
    if query.get("taxYear") is None:
        return None
    return _int_param(query["taxYear"], "taxYear")


@_property_scoped
def _property_checklist(wiring, user, params, body, query) -> dict[str, Any]:
    tax_year = _year_param(query)
    return _result_response(
        _checklist_service(wiring, user).checklist_for(params["propertyId"], tax_year)
    )


@_property_scoped
def _property_checklist_summary(wiring, user, params, body, query) -> dict[str, Any]:
    return _result_response(
        _checklist_service(wiring, user).property_summary(params["propertyId"])
    )


def _portfolio_checklist_summary(wiring, user, params, body, query) -> dict[str, Any]:
    tax_year = _year_param(query)
    return _result_response(
        _checklist_service(wiring, user).portfolio_summary(tax_year)
    )


def _carryforward_reconcile(wiring, user, params, body, query) -> dict[str, Any]:
    # GET /carryforward: the service is user-scoped and re-derives everything
    # from existing Schedule E data, so reconcile() takes no params. _to_jsonable
    # renders every Money/Decimal as a two-decimal string like the other reads.
    service = _carryforward_service_or_503(wiring, user)
    return _response(200, service.reconcile())


def _set_carryforward_reported(wiring, user, params, body, query) -> dict[str, Any]:
    # PUT /carryforward/years/{taxYear}: persist the user-entered per-year state
    # for a year. The body carries up to three INDEPENDENTLY-OPTIONAL fields, each
    # routed to the setter that owns it (design "Routes — body contract"):
    #   * amount        (string)         -> set_reported
    #   * fully_allowed (bool)           -> set_fully_allowed(bool(...))
    #   * allowed_loss  (string | null)  -> JSON null clears (clear_allowed_loss);
    #                                        otherwise set_allowed_loss(str(...))
    # An omitted field (key absent) is left untouched (no call). Operations are
    # applied in a fixed order and SHORT-CIRCUIT on the first validation failure,
    # so nothing further is persisted on a bad submission; that failing Result is
    # returned via _result_response (validation -> 400 with its field). A non-
    # integer {taxYear} becomes a clean 400 via _int_param before anything runs.
    service = _carryforward_service_or_503(wiring, user)
    tax_year = _int_param(params["taxYear"], "taxYear")

    # Fixed, deterministic order: fully_allowed, then allowed_loss, then reported.
    # Each setter validates independently; the first non-ok Result is returned
    # immediately without applying the later operations.
    if "fully_allowed" in body:
        if not isinstance(body["fully_allowed"], bool):
            raise _RouterError(
                400, "'fully_allowed' must be true or false.", field="fully_allowed"
            )
        result = service.set_fully_allowed(tax_year, body["fully_allowed"])
        if not result.is_ok:
            return _result_response(result)

    if "allowed_loss" in body:
        value = body["allowed_loss"]
        if value is None:
            result = service.clear_allowed_loss(tax_year)
        else:
            result = service.set_allowed_loss(tax_year, str(value))
        if not result.is_ok:
            return _result_response(result)

    if "amount" in body:
        return _result_response(service.set_reported(tax_year, str(body["amount"])))

    # No recognized field present: treat as a no-op success rather than writing an
    # empty reported value (preserves the item untouched).
    return _result_response(Result.success(None))


def _clear_carryforward_reported(wiring, user, params, body, query) -> dict[str, Any]:
    # DELETE /carryforward/years/{taxYear}: idempotent clear of the Reported
    # value for a year (success when absent).
    service = _carryforward_service_or_503(wiring, user)
    tax_year = _int_param(params["taxYear"], "taxYear")
    return _result_response(service.clear_reported(tax_year))


def _set_carryforward_opening(wiring, user, params, body, query) -> dict[str, Any]:
    # PUT /carryforward/opening-balance: persist the single Opening_Balance item.
    service = _carryforward_service_or_503(wiring, user)
    amount = str(body.get("amount", ""))
    return _result_response(service.set_opening_balance(amount))


# -- Backup / restore / clear --

def _export_backup(wiring, user, params, body, query) -> dict[str, Any]:
    # Export reads everything the authenticated user owns and returns a
    # BackupDocument dataclass; _to_jsonable renders it field-by-field with money
    # as two-decimal strings (design "Router" / Requirement 1, 13.1).
    service = _backup_service(wiring, user)
    return _response(200, service.export())


@_with_activity(_ActivitySpec(_backup_restore_events, purge="user"))
def _restore_backup(wiring, user, params, body, query) -> dict[str, Any]:
    # The parsed JSON object body is the backup document. The service validates
    # fully before any mutation; a validation failure maps to 400 with the
    # offending field via _result_response (Requirements 3/4/5).
    service = _backup_service(wiring, user)
    return _result_response(service.restore(body))


@_with_activity(_ActivitySpec(_no_events, purge="user"))
def _clear_backup(wiring, user, params, body, query) -> dict[str, Any]:
    service = _backup_service(wiring, user)
    return _result_response(service.clear())


# -- Business entities --

def _create_business(wiring, user, params, body, query) -> dict[str, Any]:
    service = _business_service(wiring, user)
    return _result_response(service.create(_business_input(body)), success_status=201)


def _list_businesses(wiring, user, params, body, query) -> dict[str, Any]:
    service = _business_service(wiring, user)
    return _response(200, service.list())


def _get_business(wiring, user, params, body, query) -> dict[str, Any]:
    """GET a single business, enriched with its linked property names (Req 10.2/10.3).

    The response is the business's own fields plus a ``linked_properties`` list
    of ``{id, name}`` refs so the UI can show owning-property names and never a
    raw id. ``linked_properties`` is only computed when the business resolves;
    its own failure (e.g. a wiring issue) is surfaced rather than hidden.
    """
    service = _business_service(wiring, user)
    result = service.get(params["businessId"])
    if not result.is_ok:
        return _result_response(result)
    linked = service.linked_properties(params["businessId"])
    if not linked.is_ok:
        return _result_response(linked)
    body_out = dict(_to_jsonable(result.value))
    body_out["linked_properties"] = _to_jsonable(linked.value)
    return _response(200, body_out)


def _update_business(wiring, user, params, body, query) -> dict[str, Any]:
    service = _business_service(wiring, user)
    return _result_response(
        service.update(params["businessId"], _business_input(body))
    )


def _delete_business(wiring, user, params, body, query) -> dict[str, Any]:
    service = _business_service(wiring, user)
    return _result_response(service.delete(params["businessId"]))


def _request_business_document_upload(wiring, user, params, body, query) -> dict[str, Any]:
    service = _business_service(wiring, user, require_files=True)
    return _result_response(
        service.request_document_upload(
            params["businessId"],
            str(body.get("filename", "")),
            str(body.get("content_type", body.get("contentType", ""))),
        ),
        success_status=201,
    )


def _list_business_documents(wiring, user, params, body, query) -> dict[str, Any]:
    service = _business_service(wiring, user, require_files=True)
    return _result_response(service.list_documents(params["businessId"]))


def _delete_business_document(wiring, user, params, body, query) -> dict[str, Any]:
    service = _business_service(wiring, user, require_files=True)
    return _result_response(
        service.delete_document(params["businessId"], params["documentId"])
    )


def _set_property_business(wiring, user, params, body, query) -> dict[str, Any]:
    """Set, change, or clear a property's owning business (Req 9).

    Body is ``{ "business_id": "<id>" | null }``; a ``null`` (or absent) value
    clears the link. Routes to the wired :class:`PropertyService.set_business`
    so ownership of the target business is validated. Result kinds map through
    the standard table (not_found→404, validation→400, unavailable→503).
    """
    service = _property_service_with_business(wiring, user)
    business_id = body.get("business_id", body.get("businessId"))
    if business_id is not None:
        business_id = str(business_id)
    return _result_response(service.set_business(params["propertyId"], business_id))


# --- Route table -------------------------------------------------------------
#
# Ordered (METHOD, path-template) -> handler. Path templates use {name} segments.
# ``public`` routes skip the identity requirement (none currently; the static category
# catalog). Matching is first-hit over the ordered list; more specific templates
# with the same segment count are disambiguated by literal segments in
# ``_match_path`` (e.g. ``.../transactions/{id}/receipts`` vs a 5-segment shape).

_Handler = Callable[[_Wiring, Any, dict, dict, dict], dict]

# Each entry: (method, template, handler, public)
_ROUTES: tuple[tuple[str, str, _Handler, bool], ...] = (
    # Categories (static reference data; requires sign-in, review S4)
    ("GET", "/categories", _list_categories, False),
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
    ("GET", "/properties/{propertyId}/earliest-year", _earliest_year, False),
    # Property photos
    ("POST", "/properties/{propertyId}/photos", _request_photo_upload, False),
    ("GET", "/properties/{propertyId}/photos", _list_photos, False),
    ("DELETE", "/properties/{propertyId}/photos/{photoId}", _delete_photo, False),
    ("PUT", "/properties/{propertyId}/photos/{photoId}/cover", _set_photo_cover, False),
    # Transactions
    ("POST", "/properties/{propertyId}/transactions", _create_transaction, False),
    ("GET", "/properties/{propertyId}/transactions", _list_transactions, False),
    ("GET", "/properties/{propertyId}/transactions/{transactionId}", _get_transaction, False),
    ("PUT", "/properties/{propertyId}/transactions/{transactionId}", _update_transaction, False),
    ("DELETE", "/properties/{propertyId}/transactions/{transactionId}", _delete_transaction, False),
    # Itemized expenses
    ("GET", "/properties/{propertyId}/itemized/{categoryId}", _itemized_summary, False),
    ("POST", "/properties/{propertyId}/itemized/{categoryId}/entries", _create_itemized_entry, False),
    ("PUT", "/properties/{propertyId}/itemized/{categoryId}/entries/{entryId}", _update_itemized_entry, False),
    ("DELETE", "/properties/{propertyId}/itemized/{categoryId}/entries/{entryId}", _delete_itemized_entry, False),
    ("PUT", "/properties/{propertyId}/itemized/{categoryId}/total", _set_itemized_total, False),
    ("DELETE", "/properties/{propertyId}/itemized/{categoryId}/total", _remove_itemized_total, False),
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
    # Loans (balance-anchor model: rate, monthly payment, anchor balance and
    # date). The literal "/loans/line-12-impact" route must be listed BEFORE
    # "/loans/{loanId}" (same segment count) so the static segment is not
    # captured as a loan id, mirroring /properties/enrich before
    # /properties/{propertyId}. Interest overrides accept tax years from 1900
    # through the anchor year (and years the schedule generates); the service
    # enforces that range.
    ("POST", "/properties/{propertyId}/loans", _create_loan, False),
    ("GET", "/properties/{propertyId}/loans", _list_loans, False),
    ("GET", "/properties/{propertyId}/loans/line-12-impact", _loan_line12_impact, False),
    ("GET", "/properties/{propertyId}/loans/{loanId}", _get_loan, False),
    ("PUT", "/properties/{propertyId}/loans/{loanId}", _update_loan, False),
    ("DELETE", "/properties/{propertyId}/loans/{loanId}", _delete_loan, False),
    ("GET", "/properties/{propertyId}/loans/{loanId}/schedule", _loan_schedule, False),
    ("PUT", "/properties/{propertyId}/loans/{loanId}/interest-overrides/{taxYear}", _set_interest_override, False),
    ("DELETE", "/properties/{propertyId}/loans/{loanId}/interest-overrides/{taxYear}", _clear_interest_override, False),
    # Schedule E imports. The literal "schedule-e" segment and distinct segment
    # counts (2 and 4) disambiguate these from the PDF feature's
    # /imports/{sessionId} (2-seg) and /imports/{sessionId}/drafts/... routes
    # under _match_path, so they are listed BEFORE the sibling /imports entries.
    ("POST", "/imports/schedule-e", _import_schedule_e, False),
    ("DELETE", "/imports/schedule-e/{propertyId}/{taxYear}", _remove_schedule_e_import, False),
    # Schedule E PDF extraction ("layer 2"). A distinct surface under
    # /imports/schedule-e/extractions: the literal "extractions" segment and
    # distinct segment counts (3, 5, 4) disambiguate these from
    # /imports/schedule-e (2-seg layer-1 confirm),
    # /imports/schedule-e/{propertyId}/{taxYear} (4-seg layer-1 undo), and the
    # expense /imports/{sessionId} (2-seg) under _match_path. The 4-seg GET here
    # and the 4-seg layer-1 undo DELETE share a segment count but differ by
    # method (GET vs DELETE) and by the literal "extractions" 3rd segment, so
    # _match_path (segment count + literal segments) keeps them distinct.
    ("POST", "/imports/schedule-e/extractions", _start_extraction, False),
    ("POST", "/imports/schedule-e/extractions/{jobId}/start", _begin_extraction, False),
    ("GET", "/imports/schedule-e/extractions/{jobId}", _get_extraction, False),
    # Expense imports (existing PDF feature — left untouched)
    ("POST", "/imports", _create_import, False),
    ("GET", "/imports/{sessionId}", _get_import, False),
    ("GET", "/imports/{sessionId}/drafts", _list_drafts, False),
    ("PUT", "/imports/{sessionId}/drafts/{draftId}", _update_draft, False),
    ("DELETE", "/imports/{sessionId}/drafts/{draftId}", _remove_draft, False),
    ("POST", "/imports/{sessionId}/confirm", _confirm_import, False),
    # Reports
    ("GET", "/properties/{propertyId}/report", _property_report, False),
    ("GET", "/reports/combined", _combined_report, False),
    ("POST", "/properties/{propertyId}/report/pdf", _property_report_pdf, False),
    ("POST", "/reports/combined/pdf", _combined_report_pdf, False),
    # Accountant packages
    ("POST", "/accountant-packages", _create_package, False),
    ("GET", "/accountant-packages", _list_packages, False),
    ("GET", "/accountant-packages/{jobId}", _get_package, False),
    ("DELETE", "/accountant-packages/{jobId}", _delete_package, False),
    # Backup / restore / clear
    ("GET", "/backup", _export_backup, False),
    ("POST", "/backup/restore", _restore_backup, False),
    ("POST", "/backup/clear", _clear_backup, False),
    # Dashboard
    ("GET", "/dashboard", _dashboard_portfolio, False),
    ("GET", "/dashboard/properties", _dashboard_per_property, False),
    ("GET", "/dashboard/assets", _dashboard_asset_summary, False),
    ("GET", "/dashboard/trends", _dashboard_trends, False),
    # Global search (read-only; GET only)
    ("GET", "/search", _search, False),
    # Activity history: GET only on the two lists; POST only on restore
    ("GET", "/activity", _list_activity, False),
    ("GET", "/properties/{propertyId}/activity", _list_property_activity, False),
    ("POST", "/properties/{propertyId}/activity/{eventId}/restore", _restore_activity, False),
    # Year-end checklist (read-only; GET only)
    ("GET", "/checklist/summary", _portfolio_checklist_summary, False),
    ("GET", "/properties/{propertyId}/checklist", _property_checklist, False),
    ("GET", "/properties/{propertyId}/checklist/summary", _property_checklist_summary, False),
    # Carryforward. The reconcile read, the single opening-balance item, and the
    # per-year reported entries. Both /carryforward/opening-balance and
    # /carryforward/years/{taxYear} are 2-segment PUTs under /carryforward; the
    # literal first segment ("opening-balance" vs "years") distinguishes them,
    # and _match_path prefers literal segments over {template} ones. The literal
    # opening-balance route is still placed first (mirroring /properties/enrich
    # before /properties/{propertyId}) so the templated route can never shadow it.
    ("GET", "/carryforward", _carryforward_reconcile, False),
    ("PUT", "/carryforward/opening-balance", _set_carryforward_opening, False),
    ("PUT", "/carryforward/years/{taxYear}", _set_carryforward_reported, False),
    ("DELETE", "/carryforward/years/{taxYear}", _clear_carryforward_reported, False),
    # Property <-> business link (literal "business" segment: no collision with
    # /properties/{propertyId}/{usage,notes,photos,...} which have distinct
    # literals, and 3 segments distinguish it from the 2-segment property routes)
    ("PUT", "/properties/{propertyId}/business", _set_property_business, False),
    # Business entities. Document paths (4 segments) are listed before the
    # single-id path (2 segments) for segment-count disambiguation.
    ("POST", "/businesses", _create_business, False),
    ("GET", "/businesses", _list_businesses, False),
    ("POST", "/businesses/{businessId}/documents", _request_business_document_upload, False),
    ("GET", "/businesses/{businessId}/documents", _list_business_documents, False),
    ("DELETE", "/businesses/{businessId}/documents/{documentId}", _delete_business_document, False),
    ("GET", "/businesses/{businessId}", _get_business, False),
    ("PUT", "/businesses/{businessId}", _update_business, False),
    ("DELETE", "/businesses/{businessId}", _delete_business, False),
)


#: Handlers whose bodies legitimately carry large documents and so skip the
#: per-field size limits (API Gateway still caps the whole payload).
_LARGE_BODY_HANDLERS: frozenset[Callable[..., Any]] = frozenset(
    {_restore_backup, _create_import}
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

        _check_path_ids(params)
        body = _parse_body(event)
        if route_handler not in _LARGE_BODY_HANDLERS:
            _check_body_shape(body)
        query = _query(event)

        return route_handler(wiring, user, params, body, query)
    except _RouterError as exc:
        # Router-owned request-shape problems (bad JSON, bad int, unconfigured
        # adapter). Kind is derived from the status for a consistent body shape.
        kind = {400: "validation", 503: "unavailable"}.get(exc.status, "validation")
        kind = {404: "not_found"}.get(exc.status, kind)
        out: dict[str, Any] = {"error": kind, "message": exc.message}
        if exc.field is not None:
            out["field"] = exc.field
        return _response(exc.status, out)
    except Exception as exc:  # noqa: BLE001 - last-resort guard; never leak internals
        # Logged for operators only; the client gets a generic body. Exception
        # messages can echo request values, so log types and locations only.
        _log.error("Unhandled error handling %s %r: %s", method, path, exc_summary(exc))
        return _response(
            500,
            {"error": "internal", "message": "An unexpected error occurred."},
        )
