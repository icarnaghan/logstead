import { afterEach, describe, expect, it } from "vitest";
import { getUserProfile } from "./auth";
import { clearSession, storeSession } from "./session";

/**
 * Tests for getUserProfile: it decodes the signed-in user's identity from the
 * stored Cognito ID token claims (display only; the API authorizer verifies
 * the token for real).
 */

/** Build an unsigned JWT with the given payload (header.payload.signature). */
function makeJwt(payload: Record<string, unknown>): string {
  const b64url = (obj: unknown) =>
    btoa(JSON.stringify(obj)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64url({ alg: "none", typ: "JWT" })}.${b64url(payload)}.sig`;
}

afterEach(() => {
  clearSession();
});

describe("getUserProfile", () => {
  it("returns null when there is no session", () => {
    expect(getUserProfile()).toBeNull();
  });

  it("decodes sub and email from the ID token claims", () => {
    storeSession({
      idToken: makeJwt({ sub: "abc-123", email: "you@example.com" }),
      accessToken: "access",
    });

    const profile = getUserProfile();
    expect(profile).toEqual({
      sub: "abc-123",
      email: "you@example.com",
      displayName: "you@example.com",
    });
  });

  it("falls back to sub for the display name when email is absent", () => {
    storeSession({
      idToken: makeJwt({ sub: "abc-123" }),
      accessToken: "access",
    });

    const profile = getUserProfile();
    expect(profile?.displayName).toBe("abc-123");
    expect(profile?.email).toBeUndefined();
  });

  it("returns null for a malformed token", () => {
    storeSession({ idToken: "not-a-jwt", accessToken: "access" });
    expect(getUserProfile()).toBeNull();
  });
});
