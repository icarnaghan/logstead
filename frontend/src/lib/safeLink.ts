/**
 * True only for same-app paths: starts with a single `/`, not `//`, with no
 * backslash and no control character.
 */
export function isSafeAppLink(link: string): boolean {
  if (typeof link !== 'string' || !link.startsWith('/') || link.startsWith('//')) return false
  for (let i = 0; i < link.length; i += 1) {
    const code = link.charCodeAt(i)
    if (code === 0x5c || code <= 0x1f || (code >= 0x7f && code <= 0x9f)) return false
  }
  return true
}
