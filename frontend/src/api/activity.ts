/**
 * Activity history API module (Requirements 15, 16, 17).
 *
 * Transport-only wrapper over the shared {@link apiClient}:
 *  - `GET /activity` → the user's events, newest first,
 *  - `GET /properties/{propertyId}/activity` → one property's events,
 *  - `POST /properties/{propertyId}/activity/{eventId}/restore` → re-create a
 *    restorable deleted record; returns the new record id.
 *
 * Money values inside `before` and `after` stay two-decimal strings.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

export type ActivityAction =
  | "create"
  | "update"
  | "delete"
  | "restore"
  | "import";

export type ActivityEntity =
  | "transaction"
  | "itemized_entry"
  | "asset"
  | "loan"
  | "property"
  | "backup"
  | "schedule_e";

export type ActivityValues = Record<string, string | boolean | null>;

export interface ActivityEvent {
  readonly id: string;
  /** UTC ISO timestamp. */
  readonly at: string;
  readonly action: ActivityAction;
  readonly entity: ActivityEntity;
  readonly record_id: string | null;
  readonly property_id: string | null;
  readonly property_name: string | null;
  readonly summary: string;
  readonly before: ActivityValues | null;
  readonly after: ActivityValues | null;
  readonly truncated: boolean;
  readonly restorable: boolean;
  readonly restored_as: string | null;
}

export interface ActivityPage {
  readonly events: ActivityEvent[];
  readonly next_cursor: string | null;
}

/** Response of the restore route (backend `RestoreOutcome`). */
export interface RestoreResult {
  /** Id of the re-created record (new id, not the deleted one). */
  readonly record_id: string;
  readonly event_id: string;
  readonly restored_at: string;
}

export interface ActivityListParams {
  limit?: number;
  cursor?: string | null;
  entity?: ActivityEntity | null;
  action?: ActivityAction | null;
  signal?: AbortSignal;
}

export interface GlobalActivityListParams extends ActivityListParams {
  propertyId?: string | null;
}

export class ActivityApi {
  private readonly client: ApiClient;

  constructor(client: ApiClient = apiClient) {
    this.client = client;
  }

  /** `GET /activity`. Unset or empty filters are omitted from the query. */
  list(params: GlobalActivityListParams = {}): Promise<ActivityPage> {
    const { signal, propertyId, ...rest } = params;
    return this.client.get<ActivityPage>("/activity", {
      query: { ...toQuery(rest), propertyId: propertyId || undefined },
      signal,
    });
  }

  /** `GET /properties/{propertyId}/activity`. */
  listForProperty(
    propertyId: string,
    params: ActivityListParams = {},
  ): Promise<ActivityPage> {
    const { signal, ...rest } = params;
    return this.client.get<ActivityPage>(
      `/properties/${encodeURIComponent(propertyId)}/activity`,
      { query: toQuery(rest), signal },
    );
  }

  /** `POST /properties/{propertyId}/activity/{eventId}/restore`. */
  restore(
    propertyId: string,
    eventId: string,
    signal?: AbortSignal,
  ): Promise<RestoreResult> {
    return this.client.post<RestoreResult>(
      `/properties/${encodeURIComponent(propertyId)}/activity/${encodeURIComponent(eventId)}/restore`,
      { signal },
    );
  }
}

function toQuery(
  p: Omit<ActivityListParams, "signal">,
): Record<string, string | number | undefined> {
  return {
    limit: p.limit,
    cursor: p.cursor || undefined,
    entity: p.entity || undefined,
    action: p.action || undefined,
  };
}

/** Shared instance wired to the app's singleton API client. */
export const activityApi = new ActivityApi();
