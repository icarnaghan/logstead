import { useEffect, useRef } from 'react'

export type FormValues = Readonly<Record<string, string | boolean | number | null>>

/**
 * True iff the two value maps differ: different key sets or any value that is
 * not strictly equal. No trimming or normalization is applied.
 */
export function isDirty(initial: FormValues, current: FormValues): boolean {
  const initialKeys = Object.keys(initial)
  const currentKeys = Object.keys(current)
  if (initialKeys.length !== currentKeys.length) return true
  for (const key of initialKeys) {
    if (!Object.prototype.hasOwnProperty.call(current, key)) return true
    if (initial[key] !== current[key]) return true
  }
  return false
}

/**
 * Reports changes of the derived dirty value to `onDirtyChange`, and reports
 * `false` when the component unmounts.
 */
export function useDirtyReporter(
  initial: FormValues,
  current: FormValues,
  onDirtyChange?: (dirty: boolean) => void,
): void {
  const dirty = isDirty(initial, current)
  const callbackRef = useRef(onDirtyChange)
  const lastReported = useRef(false)

  useEffect(() => {
    callbackRef.current = onDirtyChange
  })

  useEffect(() => {
    if (lastReported.current === dirty) return
    lastReported.current = dirty
    callbackRef.current?.(dirty)
  }, [dirty])

  useEffect(() => {
    return () => {
      lastReported.current = false
      callbackRef.current?.(false)
    }
  }, [])
}
