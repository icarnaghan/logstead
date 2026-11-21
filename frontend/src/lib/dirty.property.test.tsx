import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { useState } from 'react'
import { render, act } from '@testing-library/react'
import { isDirty, useDirtyReporter, type FormValues } from './dirty'

const valueArb = fc.oneof(
  fc.string(),
  fc.boolean(),
  fc.integer(),
  fc.constant(null),
)

const keysArb = fc.uniqueArray(fc.string({ minLength: 1, maxLength: 6 }), {
  minLength: 0,
  maxLength: 6,
})

/** Two records sharing the same key set. */
const pairArb = keysArb.chain((keys) =>
  fc
    .tuple(
      fc.array(valueArb, { minLength: keys.length, maxLength: keys.length }),
      fc.array(valueArb, { minLength: keys.length, maxLength: keys.length }),
    )
    .map(([a, b]) => {
      const initial: Record<string, string | boolean | number | null> = {}
      const current: Record<string, string | boolean | number | null> = {}
      keys.forEach((k, i) => {
        Object.defineProperty(initial, k, { value: a[i], enumerable: true, writable: true, configurable: true })
        Object.defineProperty(current, k, { value: b[i], enumerable: true, writable: true, configurable: true })
      })
      return { keys, initial: initial as FormValues, current: current as FormValues }
    }),
)

describe('isDirty properties', () => {
  // Feature: ui-polish-and-consistency, Property 1: Dirty state is exactly "values differ"
  // **Validates: Requirements 10.1**
  it('is true iff at least one key has a different value', () => {
    fc.assert(
      fc.property(pairArb, ({ keys, initial, current }) => {
        const differs = keys.some((k) => !Object.is(initial[k], current[k]) && initial[k] !== current[k])
        expect(isDirty(initial, current)).toBe(differs)
      }),
      { numRuns: 100 },
    )
  })

  // Feature: ui-polish-and-consistency, Property 1: Dirty state is exactly "values differ"
  // **Validates: Requirements 10.1**
  it('isDirty(v, v) is false for every v', () => {
    fc.assert(
      fc.property(pairArb, ({ initial }) => {
        expect(isDirty(initial, initial)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })
})

type Setter = (updater: (prev: FormValues) => FormValues) => void

function Harness({
  initial,
  onDirtyChange,
  setterRef,
}: {
  initial: FormValues
  onDirtyChange: (dirty: boolean) => void
  setterRef: { current: Setter | null }
}) {
  const [current, setCurrent] = useState<FormValues>(initial)
  setterRef.current = setCurrent
  useDirtyReporter(initial, current, onDirtyChange)
  return null
}

describe('useDirtyReporter properties', () => {
  // Feature: ui-polish-and-consistency, Property 2: Editing and then restoring returns to clean
  // **Validates: Requirements 10.7**
  it('reports clean after edits followed by restoring every edited field', () => {
    const scenarioArb = fc
      .array(valueArb, { minLength: 1, maxLength: 5 })
      .chain((initialValues) =>
        fc.record({
          initialValues: fc.constant(initialValues),
          edits: fc.array(
            fc.record({
              index: fc.integer({ min: 0, max: initialValues.length - 1 }),
              value: valueArb,
            }),
            { maxLength: 10 },
          ),
        }),
      )

    fc.assert(
      fc.property(scenarioArb, ({ initialValues, edits }) => {
        const initial: FormValues = Object.fromEntries(initialValues.map((v, i) => [`f${i}`, v]))
        const reports: boolean[] = []
        const setterRef: { current: Setter | null } = { current: null }
        const { unmount } = render(
          <Harness initial={initial} onDirtyChange={(d) => reports.push(d)} setterRef={setterRef} />,
        )
        try {
          for (const { index, value } of edits) {
            act(() => setterRef.current!((prev) => ({ ...prev, [`f${index}`]: value })))
          }
          const edited = new Set(edits.map((e) => e.index))
          for (const index of edited) {
            act(() => setterRef.current!((prev) => ({ ...prev, [`f${index}`]: initialValues[index] })))
          }
          // No report at all means it was never dirty, i.e. still clean.
          expect(reports.length === 0 || reports[reports.length - 1] === false).toBe(true)
        } finally {
          unmount()
        }
      }),
      { numRuns: 100 },
    )
  })
})
