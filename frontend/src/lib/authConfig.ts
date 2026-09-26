/**
 * Cognito Hosted UI (OIDC / OAuth2 Authorization Code + PKCE) configuration.
 *
 * Values are read from Vite env vars (`import.meta.env.VITE_COGNITO_*`) so the
 * same build can target different Cognito User Pools per environment. The
 * config is resolved lazily so tests can override individual values without a
 * rebuild.
 *
 * See `.env.example` for the full set of variables.
 */

/** Resolved Cognito Hosted UI configuration used by the auth flow. */
export interface AuthConfig {
  /**
   * Cognito domain origin, e.g. `https://my-app.auth.us-east-1.amazoncognito.com`.
   * A trailing slash is stripped so endpoint URLs join predictably.
   */
  domain: string;
  /** App client id registered on the User Pool. */
  clientId: string;
  /** SPA callback URL registered on the app client (the `/auth/callback` route). */
  redirectUri: string;
  /** Post-logout redirect URL registered on the app client. */
  logoutUri: string;
  /** OAuth2 scopes requested at the authorize endpoint. */
  scopes: string[];
}

const DEFAULT_SCOPES = ["openid", "email", "profile"];

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

/**
 * Read the Cognito configuration from Vite env vars.
 *
 * `VITE_COGNITO_SCOPES` is an optional space-separated list; when unset it
 * defaults to `openid email profile`. Missing required values resolve to empty
 * strings so callers can surface a clear "auth not configured" error rather
 * than crashing at import time.
 */
export function getAuthConfig(): AuthConfig {
  const env = import.meta.env;
  const scopesRaw = env.VITE_COGNITO_SCOPES?.trim();
  const scopes = scopesRaw
    ? scopesRaw.split(/\s+/).filter(Boolean)
    : DEFAULT_SCOPES;

  return {
    domain: stripTrailingSlash(env.VITE_COGNITO_DOMAIN ?? ""),
    clientId: env.VITE_COGNITO_CLIENT_ID ?? "",
    redirectUri: env.VITE_COGNITO_REDIRECT_URI ?? "",
    logoutUri: env.VITE_COGNITO_LOGOUT_URI ?? "",
    scopes,
  };
}

/** True when the minimum config needed to start the OIDC flow is present. */
export function isAuthConfigured(config: AuthConfig = getAuthConfig()): boolean {
  return Boolean(config.domain && config.clientId && config.redirectUri);
}

/** Cognito Hosted UI authorize endpoint for the given config. */
export function authorizeEndpoint(config: AuthConfig): string {
  return `${config.domain}/oauth2/authorize`;
}

/** Cognito token endpoint (authorization code exchange) for the given config. */
export function tokenEndpoint(config: AuthConfig): string {
  return `${config.domain}/oauth2/token`;
}

/** Cognito Hosted UI logout endpoint for the given config. */
export function logoutEndpoint(config: AuthConfig): string {
  return `${config.domain}/logout`;
}
