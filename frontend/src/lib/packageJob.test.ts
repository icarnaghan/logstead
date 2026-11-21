import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  POLL_INTERVAL_MS,
  formatBytes,
  isTerminal,
  linkMinutes,
  startDownload,
  statusLabel,
} from './packageJob'

describe('packageJob helpers', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('polls every 3 seconds', () => {
    expect(POLL_INTERVAL_MS).toBe(3000)
  })

  it('treats only complete and failed as terminal', () => {
    expect(isTerminal('queued')).toBe(false)
    expect(isTerminal('running')).toBe(false)
    expect(isTerminal('complete')).toBe(true)
    expect(isTerminal('failed')).toBe(true)
  })

  it('labels every status', () => {
    expect(statusLabel('queued')).toBe('Waiting to start')
    expect(statusLabel('running')).toBe('Preparing your package')
    expect(statusLabel('complete')).toBe('Package ready')
    expect(statusLabel('failed')).toBe('Package failed')
  })

  it('formats byte sizes', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(1023)).toBe('1023 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1536 * 1024)).toBe('1.5 MB')
    expect(formatBytes(419430400)).toBe('400.0 MB')
    expect(formatBytes(-5)).toBe('0 B')
  })

  it('rounds link validity up to whole minutes', () => {
    expect(linkMinutes(900)).toBe(15)
    expect(linkMinutes(61)).toBe(2)
    expect(linkMinutes(10)).toBe(1)
    expect(linkMinutes(0)).toBe(1)
  })

  it('startDownload assigns the location', () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { assign })
    startDownload('https://example.com/a.zip')
    expect(assign).toHaveBeenCalledWith('https://example.com/a.zip')
  })
})
