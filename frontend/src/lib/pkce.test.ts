import { describe, expect, it } from "vitest";
import {
  base64UrlEncode,
  createPkcePair,
  deriveCodeChallenge,
  generateCodeVerifier,
  generateState,
} from "./pkce";

describe("pkce", () => {
  it("base64url-encodes without padding or url-unsafe chars", () => {
    // Bytes chosen to produce '+' and '/' under standard base64.
    const bytes = new Uint8Array([0xfb, 0xff, 0xbf]);
    const encoded = base64UrlEncode(bytes);
    expect(encoded).not.toContain("+");
    expect(encoded).not.toContain("/");
    expect(encoded).not.toContain("=");
    expect(encoded).toBe("-_-_");
  });

  it("generates a verifier within the RFC 7636 length range", () => {
    const verifier = generateCodeVerifier();
    expect(verifier.length).toBeGreaterThanOrEqual(43);
    expect(verifier.length).toBeLessThanOrEqual(128);
    expect(verifier).toMatch(/^[A-Za-z0-9\-_]+$/);
  });

  it("derives a stable S256 challenge for a known verifier", async () => {
    // Well-known RFC 7636 Appendix B test vector.
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    const challenge = await deriveCodeChallenge(verifier);
    expect(challenge).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  it("produces matching verifier/challenge pairs", async () => {
    const { verifier, challenge } = await createPkcePair();
    const recomputed = await deriveCodeChallenge(verifier);
    expect(challenge).toBe(recomputed);
  });

  it("generates a url-safe state value", () => {
    const state = generateState();
    expect(state).toMatch(/^[A-Za-z0-9\-_]+$/);
    expect(state.length).toBeGreaterThan(0);
  });
});
