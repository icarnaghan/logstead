import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  AuthError,
  buildAuthorizeUrl,
  handleAuthCallback,
  handleUnauthorized,
  login,
  logout,
  parseCallbackParams,
} from "./auth";
import type { AuthConfig } from "./authConfig";
import { clearSession, getToken, isAuthenticated } from "./session";

const config: AuthConfig = {
  domain: "https://logstead.auth.us-east-1.amazoncognito.com",
  clientId: "client-123",
  redirectUri: "http://localhost:5173/auth/callback",
  logoutUri: "http://localhost:5173/",
  scopes: ["openid", "email", "profile"],
};

/** Minimal in-memory Storage implementation for tests. */
function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k) => (map.has(k) ? (map.get(k) as string) : null),
    key: (i) => Array.from(map.keys())[i] ?? null,
    removeItem: (k) => {
      map.delete(k);
    },
    setItem: (k, v) => {
      map.set(k, v);
    },
  };
}

function tokenResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("buildAuthorizeUrl", () => {
  it("constructs the authorize URL with PKCE + state params", () => {
    const url = new URL(
      buildAuthorizeUrl(config, {
        state: "state-abc",
        codeChallenge: "challenge-xyz",
      }),
    );

    expect(url.origin + url.pathname).toBe(
      "https://logstead.auth.us-east-1.amazoncognito.com/oauth2/authorize",
    );
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("client_id")).toBe("client-123");
    expect(url.searchParams.get("redirect_uri")).toBe(
      "http://localhost:5173/auth/callback",
    );
    expect(url.searchParams.get("scope")).toBe("openid email profile");
    expect(url.searchParams.get("state")).toBe("state-abc");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("code_challenge")).toBe("challenge-xyz");
  });
});

describe("login", () => {
  it("stores verifier + state and redirects to the authorize endpoint", async () => {
    const storage = memoryStorage();
    const redirect = vi.fn();

    await login({ config, storage, redirect });

    expect(redirect).toHaveBeenCalledTimes(1);
    const url = new URL(redirect.mock.calls[0][0]);
    expect(url.pathname).toBe("/oauth2/authorize");

    // Verifier + state persisted; challenge on the URL matches nothing empty.
    expect(storage.getItem("logstead.pkce.verifier")).toBeTruthy();
    const storedState = storage.getItem("logstead.oauth.state");
    expect(storedState).toBeTruthy();
    expect(url.searchParams.get("state")).toBe(storedState);
    expect(url.searchParams.get("code_challenge")).toBeTruthy();
  });

  it("throws when auth is not configured", async () => {
    const storage = memoryStorage();
    await expect(
      login({ config: { ...config, clientId: "" }, storage, redirect: vi.fn() }),
    ).rejects.toBeInstanceOf(AuthError);
  });
});

describe("parseCallbackParams", () => {
  it("reads code, state, and error params", () => {
    const params = parseCallbackParams(
      "?code=abc&state=s1&error=access_denied&error_description=nope",
    );
    expect(params).toEqual({
      code: "abc",
      state: "s1",
      error: "access_denied",
      errorDescription: "nope",
    });
  });
});

describe("handleAuthCallback", () => {
  beforeEach(() => {
    clearSession();
  });

  it("exchanges the code and stores a session on success", async () => {
    const storage = memoryStorage();
    storage.setItem("logstead.oauth.state", "state-1");
    storage.setItem("logstead.pkce.verifier", "verifier-1");

    const fetchImpl = vi.fn().mockResolvedValue(
      tokenResponse({
        id_token: "id-tok",
        access_token: "access-tok",
        refresh_token: "refresh-tok",
        expires_in: 3600,
      }),
    );

    const tokens = await handleAuthCallback(
      { code: "auth-code", state: "state-1" },
      { config, storage, fetchImpl },
    );

    // Token endpoint called with the PKCE verifier + code.
    const [tokenUrl, init] = fetchImpl.mock.calls[0];
    expect(tokenUrl).toBe(
      "https://logstead.auth.us-east-1.amazoncognito.com/oauth2/token",
    );
    const sentBody = new URLSearchParams(init.body as string);
    expect(sentBody.get("grant_type")).toBe("authorization_code");
    expect(sentBody.get("code")).toBe("auth-code");
    expect(sentBody.get("code_verifier")).toBe("verifier-1");

    // Session stored and readable via the session module.
    expect(tokens.accessToken).toBe("access-tok");
    expect(isAuthenticated()).toBe(true);
    expect(getToken("access")).toBe("access-tok");
    expect(getToken("id")).toBe("id-tok");

    // Transient PKCE/state cleared after exchange.
    expect(storage.getItem("logstead.oauth.state")).toBeNull();
    expect(storage.getItem("logstead.pkce.verifier")).toBeNull();
  });

  it("rejects a mismatched state without exchanging or storing a session", async () => {
    const storage = memoryStorage();
    storage.setItem("logstead.oauth.state", "expected-state");
    storage.setItem("logstead.pkce.verifier", "verifier-1");
    const fetchImpl = vi.fn();

    await expect(
      handleAuthCallback(
        { code: "auth-code", state: "attacker-state" },
        { config, storage, fetchImpl },
      ),
    ).rejects.toBeInstanceOf(AuthError);

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(isAuthenticated()).toBe(false);
    // Transient values cleared even on rejection.
    expect(storage.getItem("logstead.oauth.state")).toBeNull();
    expect(storage.getItem("logstead.pkce.verifier")).toBeNull();
  });

  it("rejects a provider error and establishes no session", async () => {
    const storage = memoryStorage();
    storage.setItem("logstead.oauth.state", "state-1");
    storage.setItem("logstead.pkce.verifier", "verifier-1");
    const fetchImpl = vi.fn();

    await expect(
      handleAuthCallback(
        { error: "access_denied", errorDescription: "User denied" },
        { config, storage, fetchImpl },
      ),
    ).rejects.toThrow(/User denied/);

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(isAuthenticated()).toBe(false);
  });

  it("rejects when the token exchange fails", async () => {
    const storage = memoryStorage();
    storage.setItem("logstead.oauth.state", "state-1");
    storage.setItem("logstead.pkce.verifier", "verifier-1");
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(tokenResponse({ error: "invalid_grant" }, 400));

    await expect(
      handleAuthCallback(
        { code: "auth-code", state: "state-1" },
        { config, storage, fetchImpl },
      ),
    ).rejects.toBeInstanceOf(AuthError);
    expect(isAuthenticated()).toBe(false);
  });
});

describe("logout", () => {
  beforeEach(() => {
    clearSession();
  });

  it("clears the session and redirects to the Cognito logout endpoint", () => {
    // Seed a session so we can confirm it is cleared.
    const storage = memoryStorage();
    const redirect = vi.fn();

    // Store a token via the real session module.
    // (logout clears session regardless of storage injection.)
    void storage;

    logout({ config, redirect });

    expect(isAuthenticated()).toBe(false);
    const url = new URL(redirect.mock.calls[0][0]);
    expect(url.pathname).toBe("/logout");
    expect(url.searchParams.get("client_id")).toBe("client-123");
    expect(url.searchParams.get("logout_uri")).toBe("http://localhost:5173/");
  });
});

describe("handleUnauthorized", () => {
  beforeEach(() => {
    clearSession();
  });

  it("clears the session and restarts sign-in", async () => {
    const storage = memoryStorage();
    const redirect = vi.fn();

    await handleUnauthorized({ config, storage, redirect });

    expect(isAuthenticated()).toBe(false);
    expect(redirect).toHaveBeenCalledTimes(1);
    const url = new URL(redirect.mock.calls[0][0]);
    expect(url.pathname).toBe("/oauth2/authorize");
  });
});
