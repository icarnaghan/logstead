import type { ActivityEvent } from "../../api/activity";
import { ActivityEventRow } from "./ActivityEventRow";

/** The event list as an unordered list inside a bordered card. */
export function ActivityList({
  events,
  label,
}: {
  events: readonly ActivityEvent[];
  label: string;
}) {
  return (
    <ul
      aria-label={label}
      className="rounded-lg border border-border bg-surface"
    >
      {events.map((event) => (
        <ActivityEventRow key={event.id} event={event} />
      ))}
    </ul>
  );
}
