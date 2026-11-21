/**
 * Today's calendar date in the user's local time zone as "YYYY-MM-DD"
 * (Requirement 12.9). Built from local date parts, never `toISOString`, so
 * users near midnight UTC do not get the previous or next day.
 */
export function todayLocal(now: Date = new Date()): string {
  const year = String(now.getFullYear()).padStart(4, "0");
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
