/**
 * Cognito Hosted UI authentication flow (OIDC / OAuth2 Authorization Code +
 * PKCE).
 *
 * Responsibilities:
 *  - `login()`  — build the authorize URL with PKCE + state and redirect the
 *    browser to the Cognito Hosted UI (Requirement 1.1).
 *  - `handleAuthCallback()` — validate the returned `state`, exchange the
 *    authorization code at the token endpoint (PKCE `code_verifier`), and
 *    store the resulting tokens via the session module (Requirement 1.2). A
 *    provider error on the callback establishes no session (Requirement 1.3).
 *  - `logout()` — clear local tokens and redirect to the Cognito logout
 *    endpoint to end the provider session (Requirement 1.4).
 *  - `handleUnauthorized()` — clear the session and restart sign-in when the
 *    API returns 401.
 *
 * Network (token exchange) and browser navigation are injectable so the flow
 * is unit-testable without a real Cognito or `window.location`.
 */

import {
  authorizeEndpoint,
  getAuthConfig,
  logoutEndpoint,
  tokenEndpoint,
  type AuthConfig,
} from "./authConfig";
import { createPkcePair, generateState } from "./pkce";
import {
  clearSession,
  getIdToken,
  storeSession,
  type SessionTokens,
} from "./session";

const PKCE_VERIFIER_KEY = "logstead.pkce.verifier";
const OAUTH_STATE_KEY = "logstead.oauth.state";

/** Injectable dependencies, primarily for tests. */
export interface AuthDeps {
  config?: AuthConfig;
  fetchImpl?: typeof fetch;
  cryptoImpl?: Crypto;
  /** Performs the browser navigation for a redirect. */
  redirect?: (url: string) => void;
  /** Backing store for the PKCE verifier and state. Defaults to sessionStorage. */
  storage?: Storage;
}

/** Raw token response shape from the Cognito token endpoint. */
interface TokenResponse {
  id_token: string;
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  token_type?: string;
}

/** Error raised when the auth flow cannot proceed. */
export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}

function defaultRedirect(url: string): void {
  window.location.assign(url);
}

function resolveStorage(deps: AuthDeps): Storage {
  return deps.storage ?? window.sessionStorage;
}

function resolveConfig(deps: AuthDeps): AuthConfig {
  return deps.config ?? getAuthConfig();
}

function resolveFetch(deps: AuthDeps): typeof fetch {
  return deps.fetchImpl ?? globalThis.fetch.bind(globalThis);
}

function resolveCrypto(deps: AuthDeps): Crypto {
  return deps.cryptoImpl ?? globalThis.crypto;
}

/**
 * Build the Cognito Hosted UI authorize URL for the Authorization Code + PKCE
 * flow. Exported for testing; callers normally use {@link login}.
 */
export function buildAuthorizeUrl(
  config: AuthConfig,
  params: { state: string; codeChallenge: string },
): string {
  const query = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: config.scopes.join(" "),
    state: params.state,
    code_challenge_method: "S256",
    code_challenge: params.codeChallenge,
  });
  return `${authorizeEndpoint(config)}?${query.toString()}`;
}

/**
 * Start sign-in: generate PKCE + state, persist them, and redirect the browser
 * to the Cognito Hosted UI (Requirement 1.1).
 */
export async function login(deps: AuthDeps = {}): Promise<void> {
  const config = resolveConfig(deps);
  if (!config.domain || !config.clientId || !config.redirectUri) {
    throw new AuthError("Cognito auth is not configured");
  }

  const storage = resolveStorage(deps);
  const cryptoImpl = resolveCrypto(deps);
  const redirect = deps.redirect ?? defaultRedirect;

  const { verifier, challenge } = await createPkcePair(cryptoImpl);
  const state = generateState(cryptoImpl);

  storage.setItem(PKCE_VERIFIER_KEY, verifier);
  storage.setItem(OAUTH_STATE_KEY, state);

  const url = buildAuthorizeUrl(config, { state, codeChallenge: challenge });
  redirect(url);
}

/** Parsed query params from the Hosted UI redirect back to `/auth/callback`. */
export interface CallbackParams {
  code?: string | null;
  state?: string | null;
  error?: string | null;
  errorDescription?: string | null;
}

/** Extract the OAuth callback params from a query string or URLSearchParams. */
export function parseCallbackParams(
  search: string | URLSearchParams,
): CallbackParams {
  const params =
    typeof search === "string" ? new URLSearchParams(search) : search;
  return {
    code: params.get("code"),
    state: params.get("state"),
    error: params.get("error"),
    errorDescription: params.get("error_description"),
  };
}

/**
 * Handle the Hosted UI redirect: validate state, exchange the code for tokens,
 * and store the session (Requirements 1.2, 1.3).
 *
 * Throws {@link AuthError} on a provider error, a missing/mismatched state, or
 * a failed token exchange. On any failure the stored verifier/state are cleared
 * and no session is established.
 */
export async function handleAuthCallback(
  params: CallbackParams,
  deps: AuthDeps = {},
): Promise<SessionTokens> {
  const config = resolveConfig(deps);
  const storage = resolveStorage(deps);
  const fetchImpl = resolveFetch(deps);

  const storedState = storage.getItem(OAUTH_STATE_KEY);
  const verifier = storage.getItem(PKCE_VERIFIER_KEY);

  const cleanup = () => {
    storage.removeItem(OAUTH_STATE_KEY);
    storage.removeItem(PKCE_VERIFIER_KEY);
  };

  // Provider-side failure or denial: establish no session (Requirement 1.3).
  if (params.error) {
    cleanup();
    throw new AuthError(
      params.errorDescription || params.error || "Authentication failed",
    );
  }

  if (!params.code) {
    cleanup();
    throw new AuthError("Missing authorization code");
  }

  // State must match the value we stored before redirecting (CSRF defense).
  if (!params.state || !storedState || params.state !== storedState) {
    cleanup();
    throw new AuthError("Invalid or missing state parameter");
  }

  if (!verifier) {
    cleanup();
    throw new AuthError("Missing PKCE verifier");
  }

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.clientId,
    code: params.code,
    redirect_uri: config.redirectUri,
    code_verifier: verifier,
  });

  let response: Response;
  try {
    response = await fetchImpl(tokenEndpoint(config), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  } catch (cause) {
    cleanup();
    throw new AuthError("Token exchange request failed");
  }

  if (!response.ok) {
    cleanup();
    throw new AuthError(`Token exchange failed with status ${response.status}`);
  }

  const data = (await response.json()) as TokenResponse;
  if (!data.id_token || !data.access_token) {
    cleanup();
    throw new AuthError("Token response missing tokens");
  }

  const tokens: SessionTokens = {
    idToken: data.id_token,
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    expiresAt:
      typeof data.expires_in === "number"
        ? Date.now() + data.expires_in * 1000
        : undefined,
  };

  storeSession(tokens);
  cleanup();
  return tokens;
}

/**
 * Sign out: clear the local session and redirect to the Cognito logout
 * endpoint so the provider session is also ended (Requirement 1.4).
 */
export function logout(deps: AuthDeps = {}): void {
  const config = resolveConfig(deps);
  const redirect = deps.redirect ?? defaultRedirect;

  clearSession();

  if (!config.domain || !config.clientId) {
    // Nothing to redirect to; local session is already cleared.
    return;
  }

  const query = new URLSearchParams({
    client_id: config.clientId,
    logout_uri: config.logoutUri,
  });
  redirect(`${logoutEndpoint(config)}?${query.toString()}`);
}

/**
 * Handle an API 401 by clearing the session and restarting sign-in
 * (Requirements 1.1, 1.3). Returns the `login()` promise so callers may await
 * the redirect kickoff.
 */
export function handleUnauthorized(deps: AuthDeps = {}): Promise<void> {
  clearSession();
  return login(deps);
}

/**
 * The signed-in user's profile, decoded from the Cognito ID token claims.
 *
 * The ID token is a JWT whose payload carries the user's identity claims
 * (`sub`, `email`, etc.). We read them client-side for display only - the API
 * still authorizes every request against the token via the JWT authorizer.
 */
export interface UserProfile {
  /** Cognito subject (stable unique user id). */
  sub: string;
  /** The user's email, when present in the token claims. */
  email?: string;
  /** A human-friendly display name: the email, else the sub. */
  displayName: string;
}

/** Decode a JWT payload (the middle segment) without verifying the signature. */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length < 2) return null;
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(
      base64.length + ((4 - (base64.length % 4)) % 4),
      "=",
    );
    const json = atob(padded);
    const parsed = JSON.parse(json);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Return the current user's profile from the stored ID token, or `null` when
 * there is no session or the token cannot be read. For display only; the token
 * signature is not verified client-side (the API authorizer does that).
 */
export function getUserProfile(): UserProfile | null {
  const idToken = getIdToken();
  if (!idToken) return null;
  const claims = decodeJwtPayload(idToken);
  if (!claims) return null;
  const sub = typeof claims.sub === "string" ? claims.sub : "";
  if (!sub) return null;
  const email = typeof claims.email === "string" ? claims.email : undefined;
  return { sub, email, displayName: email || sub };
}
