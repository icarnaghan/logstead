/**
 * Auth/session module.
 *
 * Owns storage and retrieval of the Cognito tokens (id/access token) on the
 * client. This is the seam the Hosted UI redirect/code-exchange flow (task
 * 20.1) writes into via {@link storeSession}, and that the API client reads
 * from via {@link getToken} to attach a Bearer Authorization header.
 *
 * Token storage uses `sessionStorage` so tokens are cleared when the tab
 * closes. The actual OIDC Authorization Code + PKCE exchange is implemented in
 * task 20.1; this module only provides storage and accessors.
 */

const ID_TOKEN_KEY = "logstead.idToken";
const ACCESS_TOKEN_KEY = "logstead.accessToken";
const REFRESH_TOKEN_KEY = "logstead.refreshToken";
const EXPIRES_AT_KEY = "logstead.expiresAt";

export interface SessionTokens {
  /** Cognito ID token (JWT). */
  idToken: string;
  /** Cognito access token (JWT). */
  accessToken: string;
  /** Optional refresh token. */
  refreshToken?: string;
  /**
   * Absolute expiry as epoch milliseconds. Derived by the caller from the
   * token `expires_in` at exchange time.
   */
  expiresAt?: number;
}

/**
 * The token the API client attaches to protected requests.
 *
 * API Gateway's native JWT authorizer accepts either the Cognito access or ID
 * token; the access token is used by convention.
 */
export type AuthToken = "access" | "id";

let store: Storage | null = null;

function storage(): Storage | null {
  if (store) return store;
  try {
    store = window.sessionStorage;
    return store;
  } catch {
    // sessionStorage unavailable (e.g. SSR/tests without jsdom storage).
    return null;
  }
}

/** Persist the tokens obtained from the Cognito token exchange. */
export function storeSession(tokens: SessionTokens): void {
  const s = storage();
  if (!s) return;
  s.setItem(ID_TOKEN_KEY, tokens.idToken);
  s.setItem(ACCESS_TOKEN_KEY, tokens.accessToken);
  if (tokens.refreshToken) {
    s.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken);
  }
  if (typeof tokens.expiresAt === "number") {
    s.setItem(EXPIRES_AT_KEY, String(tokens.expiresAt));
  }
}

/**
 * Return the bearer token to send with API requests, or `null` when there is
 * no stored session or the stored session has expired.
 */
export function getToken(which: AuthToken = "access"): string | null {
  const s = storage();
  if (!s) return null;
  if (isExpired()) return null;
  const key = which === "access" ? ACCESS_TOKEN_KEY : ID_TOKEN_KEY;
  return s.getItem(key);
}

/** Return the stored ID token, or `null`. */
export function getIdToken(): string | null {
  return getToken("id");
}

/** Return the stored refresh token, or `null`. */
export function getRefreshToken(): string | null {
  const s = storage();
  return s?.getItem(REFRESH_TOKEN_KEY) ?? null;
}

/** True when a non-expired access token is present. */
export function isAuthenticated(): boolean {
  return getToken("access") !== null;
}

/** True when a stored session exists but its expiry has passed. */
export function isExpired(): boolean {
  const s = storage();
  if (!s) return false;
  const raw = s.getItem(EXPIRES_AT_KEY);
  if (!raw) return false;
  const expiresAt = Number(raw);
  if (!Number.isFinite(expiresAt)) return false;
  return Date.now() >= expiresAt;
}

/** Remove all locally stored tokens. Used on sign-out and on 401 handling. */
export function clearSession(): void {
  const s = storage();
  if (!s) return;
  s.removeItem(ID_TOKEN_KEY);
  s.removeItem(ACCESS_TOKEN_KEY);
  s.removeItem(REFRESH_TOKEN_KEY);
  s.removeItem(EXPIRES_AT_KEY);
}
