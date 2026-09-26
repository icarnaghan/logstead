import { beforeEach, describe, expect, it } from "vitest";
import {
  clearSession,
  getIdToken,
  getToken,
  isAuthenticated,
  storeSession,
} from "./session";

describe("session", () => {
  beforeEach(() => {
    clearSession();
  });

  it("reports no authentication before a session is stored", () => {
    expect(isAuthenticated()).toBe(false);
    expect(getToken("access")).toBeNull();
  });

  it("stores and reads back access and id tokens", () => {
    storeSession({ idToken: "id-abc", accessToken: "access-xyz" });

    expect(getToken("access")).toBe("access-xyz");
    expect(getIdToken()).toBe("id-abc");
    expect(isAuthenticated()).toBe(true);
  });

  it("clears the stored session", () => {
    storeSession({ idToken: "id-abc", accessToken: "access-xyz" });
    clearSession();

    expect(isAuthenticated()).toBe(false);
    expect(getToken("access")).toBeNull();
  });

  it("treats an expired session as unauthenticated", () => {
    storeSession({
      idToken: "id-abc",
      accessToken: "access-xyz",
      expiresAt: Date.now() - 1000,
    });

    expect(isAuthenticated()).toBe(false);
    expect(getToken("access")).toBeNull();
  });
});
