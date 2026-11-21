/**
 * API client module.
 *
 * Centralizes all calls to the Logstead HTTP API. It:
 *  - resolves the backend base URL from the `VITE_API_BASE_URL` env var,
 *  - attaches the Cognito bearer token (from the session module) as an
 *    `Authorization: Bearer <token>` header,
 *  - serializes/parses JSON bodies,
 *  - surfaces non-2xx responses as a typed {@link ApiError}.
 *
 * It is intentionally transport-only: it holds no business rules and is easy
 * to unit test by injecting a `fetch` implementation and a token provider.
 */

import { getToken } from "./session";
import { handleUnauthorized } from "./auth";

/** Error thrown for non-2xx API responses. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** True for 401 responses, which callers map to a Hosted UI redirect. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

export interface ApiClientOptions {
  /** Backend base URL. Defaults to `import.meta.env.VITE_API_BASE_URL`. */
  baseUrl?: string;
  /** Supplies the bearer token. Defaults to the session module's `getToken`. */
  getAuthToken?: () => string | null;
  /** Injectable fetch, primarily for tests. Defaults to global `fetch`. */
  fetchImpl?: typeof fetch;
  /**
   * Invoked when a request returns 401. The shared instance wires this to the
   * auth flow's `handleUnauthorized` (clear session + restart Hosted UI
   * sign-in). The originating {@link ApiError} is still thrown so callers can
   * abort their in-flight work.
   */
  onUnauthorized?: (error: ApiError) => void;
}

export interface RequestOptions {
  /** Query string parameters appended to the path. */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Parsed and sent as a JSON body. */
  body?: unknown;
  /** Extra headers merged over the defaults. */
  headers?: Record<string, string>;
  /** AbortSignal for cancellation. */
  signal?: AbortSignal;
}

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

function resolveBaseUrl(explicit?: string): string {
  const base = explicit ?? import.meta.env.VITE_API_BASE_URL ?? "";
  // Strip a single trailing slash so path joining is predictable.
  return base.replace(/\/+$/, "");
}

/** Thrown when a request path could target anything other than the API origin. */
export class UnsafeApiPathError extends Error {
  constructor(path: string) {
    super(`Refusing to send request: path is not relative to the API origin (${JSON.stringify(path)})`);
    this.name = "UnsafeApiPathError";
  }
}

// Placeholder origin used only to resolve paths when no absolute base is set.
const RELATIVE_BASE = "http://relative.invalid";

/**
 * Join `path` onto `baseUrl`, guaranteeing the result stays on the base origin
 * (and under its path prefix). The bearer token is attached to this URL, so
 * absolute URLs, protocol-relative (`//host`), backslash tricks, control
 * characters and dot-segment traversal are all rejected.
 */
function buildUrl(
  baseUrl: string,
  path: string,
  query?: RequestOptions["query"],
): string {
  // eslint-disable-next-line no-control-regex
  const hasControl = /[\u0000-\u001f\u007f\\]/.test(path);
  const hasScheme = /^\s*[a-z][a-z0-9+.-]*:/i.test(path);
  const segments = path.split("?")[0].split("#")[0].split("/");
  const hasDotSegment = segments.some((seg) => {
    // WHATWG treats only ".", ".." and their %2e forms as dot segments;
    // %2F / %5C inside a segment are not separators. Undecodable segments
    // are sent verbatim and cannot form a dot segment.
    const lower = seg.toLowerCase().replace(/%2e/g, ".");
    return lower === ".." || lower === ".";
  });
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (
    hasControl ||
    hasScheme ||
    hasDotSegment ||
    normalizedPath.startsWith("//")
  ) {
    throw new UnsafeApiPathError(path);
  }

  const joined = `${baseUrl}${normalizedPath}`;
  const base = new URL(baseUrl || "/", RELATIVE_BASE);
  const resolved = new URL(joined, RELATIVE_BASE);
  const basePrefix = base.pathname.replace(/\/+$/, "");
  if (
    resolved.origin !== base.origin ||
    !(
      resolved.pathname === basePrefix ||
      resolved.pathname.startsWith(`${basePrefix}/`)
    )
  ) {
    throw new UnsafeApiPathError(path);
  }

  let url = baseUrl ? resolved.href : joined;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    params.append(key, String(value));
  }
  const qs = params.toString();
  if (qs) url += url.includes("?") ? `&${qs}` : `?${qs}`;
  return url;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getAuthToken: () => string | null;
  private readonly fetchImpl: typeof fetch;
  private readonly onUnauthorized?: (error: ApiError) => void;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = resolveBaseUrl(options.baseUrl);
    this.getAuthToken = options.getAuthToken ?? (() => getToken("access"));
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.onUnauthorized = options.onUnauthorized;
  }

  async request<T>(
    method: HttpMethod,
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const url = buildUrl(this.baseUrl, path, options.query);

    const headers: Record<string, string> = {
      Accept: "application/json",
      ...options.headers,
    };

    const token = this.getAuthToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    let bodyInit: BodyInit | undefined;
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      bodyInit = JSON.stringify(options.body);
    }

    const response = await this.fetchImpl(url, {
      method,
      headers,
      body: bodyInit,
      signal: options.signal,
    });

    const payload = await parseBody(response);

    if (!response.ok) {
      const message =
        (isRecord(payload) && typeof payload.message === "string"
          ? payload.message
          : undefined) ?? `Request failed with status ${response.status}`;
      const error = new ApiError(response.status, message, payload);
      if (error.isUnauthorized) {
        this.onUnauthorized?.(error);
      }
      throw error;
    }

    return payload as T;
  }

  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("GET", path, options);
  }

  post<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("POST", path, options);
  }

  put<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("PUT", path, options);
  }

  patch<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("PATCH", path, options);
  }

  delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("DELETE", path, options);
  }
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") ?? "";
  const text = await response.text();
  if (!text) return null;
  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Shared client instance wired to the session module and env base URL.
 *
 * On 401 it clears the session and restarts Hosted UI sign-in via the auth
 * flow's `handleUnauthorized` (Requirements 1.1, 1.3).
 */
export const apiClient = new ApiClient({
  onUnauthorized: () => {
    void handleUnauthorized();
  },
});
