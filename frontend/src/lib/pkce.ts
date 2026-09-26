/**
 * PKCE (Proof Key for Code Exchange, RFC 7636) helpers for the Authorization
 * Code + PKCE flow used with the Cognito Hosted UI.
 *
 * A high-entropy `code_verifier` is generated on the client and kept in
 * sessionStorage; its S256 `code_challenge` is sent on the authorize request.
 * At the token endpoint the original verifier proves the client that started
 * the flow is the one redeeming the code.
 *
 * Uses the Web Crypto API (`crypto.getRandomValues` + `crypto.subtle.digest`)
 * so no dependency is required. `crypto` is injectable for tests.
 */

/** Base64url-encode bytes with no padding (RFC 7636 §A). */
export function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Generate a random `code_verifier`: a base64url string of `byteLength` random
 * bytes (default 32 → 43 chars, within the RFC's 43–128 range).
 */
export function generateCodeVerifier(
  cryptoImpl: Crypto = globalThis.crypto,
  byteLength = 32,
): string {
  const random = new Uint8Array(byteLength);
  cryptoImpl.getRandomValues(random);
  return base64UrlEncode(random);
}

/**
 * Derive the S256 `code_challenge` from a `code_verifier`:
 * `BASE64URL(SHA-256(ASCII(verifier)))`.
 */
export async function deriveCodeChallenge(
  verifier: string,
  cryptoImpl: Crypto = globalThis.crypto,
): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const digest = await cryptoImpl.subtle.digest("SHA-256", data);
  return base64UrlEncode(new Uint8Array(digest));
}

/** A random URL-safe value suitable for the OAuth2 `state` parameter. */
export function generateState(cryptoImpl: Crypto = globalThis.crypto): string {
  const random = new Uint8Array(16);
  cryptoImpl.getRandomValues(random);
  return base64UrlEncode(random);
}

export interface PkcePair {
  verifier: string;
  challenge: string;
}

/** Convenience: generate a verifier and its S256 challenge together. */
export async function createPkcePair(
  cryptoImpl: Crypto = globalThis.crypto,
): Promise<PkcePair> {
  const verifier = generateCodeVerifier(cryptoImpl);
  const challenge = await deriveCodeChallenge(verifier, cryptoImpl);
  return { verifier, challenge };
}
