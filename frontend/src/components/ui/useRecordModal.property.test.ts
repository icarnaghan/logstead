import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { recordModalReducer } from "./useRecordModal";
import type { RecordModalState } from "./useRecordModal";

const recordModalStateArb: fc.Arbitrary<RecordModalState> = fc.oneof(
  fc.constant<RecordModalState>({ mode: "closed" }),
  fc.constant<RecordModalState>({ mode: "add" }),
  fc.string().map<RecordModalState>((recordId) => ({ mode: "edit", recordId })),
);

const closed: RecordModalState = { mode: "closed" };

describe("recordModalReducer properties", () => {
  // Feature: modal-forms-and-tabbed-imports, Property 1: Opening the modal is independent of prior state
  // **Validates: Requirements 2.1, 3.1, 3.7**
  it("Property 1: opening the modal is independent of prior state", () => {
    fc.assert(
      fc.property(recordModalStateArb, fc.string(), (state, id) => {
        const added = recordModalReducer(state, { type: "open-add" });
        expect(added).toEqual({ mode: "add" });
        expect(added).toEqual(recordModalReducer(closed, { type: "open-add" }));

        const edited = recordModalReducer(state, {
          type: "open-edit",
          recordId: id,
        });
        expect(edited).toEqual({ mode: "edit", recordId: id });
        expect(edited).toEqual(
          recordModalReducer(closed, { type: "open-edit", recordId: id }),
        );
      }),
      { numRuns: 100 },
    );
  });

  // Feature: modal-forms-and-tabbed-imports, Property 2: Close always ends closed and is idempotent
  // **Validates: Requirements 2.4, 3.4, 4.1, 4.2, 4.3**
  it("Property 2: close always ends closed and is idempotent", () => {
    fc.assert(
      fc.property(recordModalStateArb, (state) => {
        const once = recordModalReducer(state, { type: "close" });
        expect(once).toEqual({ mode: "closed" });
        const twice = recordModalReducer(once, { type: "close" });
        expect(twice).toEqual(once);
      }),
      { numRuns: 100 },
    );
  });

  // Feature: modal-forms-and-tabbed-imports, Property 3: Deleting a record closes the modal only when that record is being edited
  // **Validates: Requirements 3.8**
  it("Property 3: deleting a record closes the modal only when that record is being edited", () => {
    fc.assert(
      fc.property(
        recordModalStateArb,
        fc.string(),
        fc.boolean(),
        (state, randomId, useEditId) => {
          // Sometimes target the state's own edit id so the matching case is covered.
          const id =
            useEditId && state.mode === "edit" ? state.recordId : randomId;
          const result = recordModalReducer(state, {
            type: "record-deleted",
            recordId: id,
          });
          if (state.mode === "edit" && state.recordId === id) {
            expect(result).toEqual({ mode: "closed" });
          } else {
            expect(result).toBe(state);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
