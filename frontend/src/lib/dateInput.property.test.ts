import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { todayLocal } from "./dateInput";

// Feature: ui-polish-and-consistency, Property 9: Today is the local calendar date
describe("todayLocal property", () => {
  it("matches YYYY-MM-DD and equals the local year/month/day", () => {
    // **Validates: Requirements 12.9**
    fc.assert(
      fc.property(
        fc.date({
          min: new Date(1000, 0, 1),
          max: new Date(9000, 11, 31),
          noInvalidDate: true,
        }),
        (d) => {
          const s = todayLocal(d);
          expect(s).toMatch(/^\d{4}-\d{2}-\d{2}$/);
          const [y, m, day] = s.split("-").map(Number);
          expect(y).toBe(d.getFullYear());
          expect(m).toBe(d.getMonth() + 1);
          expect(day).toBe(d.getDate());
        },
      ),
      { numRuns: 100 },
    );
  });
});
