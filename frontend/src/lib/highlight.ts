export interface HighlightSegment {
  text: string
  match: boolean
}

function normalizeText(text: string): string {
  return text.normalize('NFKC').toLowerCase().replace(/\s+/g, ' ')
}

/**
 * Splits `text` into segments, marking the parts that match any token after
 * NFKC normalization and case folding. Concatenating the segments always
 * equals the original text. Rendering must use text nodes, never HTML.
 */
export function highlightSegments(text: string, tokens: readonly string[]): HighlightSegment[] {
  if (text === '') return []
  const needles = tokens.map((t) => normalizeText(t).trim()).filter((t) => t.length > 0)
  if (needles.length === 0) return [{ text, match: false }]

  // Normalize per code point so every normalized index maps to an original range.
  let normalized = ''
  const starts: number[] = [] // original start offset for each normalized UTF-16 unit
  const ends: number[] = [] // original end offset for each normalized UTF-16 unit
  let offset = 0
  for (const ch of text) {
    const norm = normalizeText(ch)
    for (let i = 0; i < norm.length; i += 1) {
      starts.push(offset)
      ends.push(offset + ch.length)
    }
    normalized += norm
    offset += ch.length
  }

  const ranges: Array<[number, number]> = []
  for (const needle of needles) {
    let from = 0
    while (from <= normalized.length - needle.length) {
      const idx = normalized.indexOf(needle, from)
      if (idx === -1) break
      ranges.push([starts[idx], ends[idx + needle.length - 1]])
      from = idx + 1
    }
  }
  if (ranges.length === 0) return [{ text, match: false }]

  ranges.sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const merged: Array<[number, number]> = []
  for (const [s, e] of ranges) {
    const last = merged[merged.length - 1]
    if (last && s <= last[1]) last[1] = Math.max(last[1], e)
    else merged.push([s, e])
  }

  const segments: HighlightSegment[] = []
  let pos = 0
  for (const [s, e] of merged) {
    if (s > pos) segments.push({ text: text.slice(pos, s), match: false })
    segments.push({ text: text.slice(s, e), match: true })
    pos = e
  }
  if (pos < text.length) segments.push({ text: text.slice(pos), match: false })
  return segments
}
