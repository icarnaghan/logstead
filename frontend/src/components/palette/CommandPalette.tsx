import * as Dialog from "@radix-ui/react-dialog";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import type { Property } from "../../api/properties";
import { cn } from "../../lib/cn";
import { isSafeAppLink } from "../../lib/safeLink";
import {
  groupLabel,
  orderedGroups,
  SEARCH_ERROR_TEXT,
  TRUNCATION_NOTICE,
} from "../search/searchGroups";
import { FOCUS_RING } from "../ui/focusRing";
import {
  isPropertyScopedAction,
  type PaletteItem,
  type PropertyScopedActionId,
} from "./paletteItems";
import { moveHighlight, rankLocal, tokenize } from "./paletteRank";
import { optionId, PaletteList, type PaletteRow } from "./PaletteList";
import {
  MIN_SEARCH_LENGTH,
  PALETTE_HITS_PER_GROUP,
  useGlobalSearch,
  type SearchFn,
} from "./useGlobalSearch";

/** Maximum local items shown (ui-polish Requirement 5.5). */
export const MAX_LOCAL_ITEMS = 8;
const ROOT_GROUP_ORDER = [
  "Pages",
  "Properties",
  "Property sections",
  "Tax years",
  "Actions",
];

/** Returned by `onRunItem` when the palette must show the property picker. */
export interface PickRequest {
  pick: PropertyScopedActionId;
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialQuery: string;
  /** All local items (the palette filters them). */
  items: readonly PaletteItem[];
  properties: readonly Pick<Property, "id" | "name">[];
  propertiesStatus: "loading" | "loaded" | "error";
  /** Runs an item. Returns a pick request for property-scoped actions. */
  onRunItem: (item: PaletteItem) => PickRequest | void;
  /** Runs the chosen property of the picker step. */
  onPickProperty: (action: PropertyScopedActionId, propertyId: string) => void;
  onCloseAutoFocus: (event: Event) => void;
  /** Opens an in-app link (search hit or "See all results"). */
  onOpenLink?: (link: string) => void;
  /** Test seam for the global search request. */
  search?: SearchFn;
}

/** What choosing a row does. */
type Entry =
  | { type: "local"; item: PaletteItem; propertyId: string }
  | { type: "link"; link: string };

/** Items shown for an empty query: page Destinations and Actions, fixed order. */
function emptyQueryItems(items: readonly PaletteItem[]): PaletteItem[] {
  return items.filter(
    (item) =>
      item.kind === "action" ||
      (item.kind === "destination" && item.group === "Pages"),
  );
}

function groupOf(item: PaletteItem): string {
  return item.kind === "action" ? "Actions" : item.group;
}

/** Stable-group rows so each group is contiguous, in order of first appearance. */
function groupContiguous<T extends { group: string }>(rows: T[]): T[] {
  const order: string[] = [];
  for (const row of rows) if (!order.includes(row.group)) order.push(row.group);
  order.sort((a, b) => {
    const ia = ROOT_GROUP_ORDER.indexOf(a);
    const ib = ROOT_GROUP_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || order.indexOf(a) - order.indexOf(b);
  });
  return order.flatMap((group) => rows.filter((row) => row.group === group));
}

/**
 * Command palette dialog (ui-polish Requirements 1.x, 4.x, 5.x). The content
 * mounts only while open, so the query, step and highlight reset on each open.
 */
export function CommandPalette(props: CommandPaletteProps) {
  return (
    <Dialog.Root open={props.open} onOpenChange={props.onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-fg/40" />
        <PaletteContent {...props} />
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PaletteContent({
  initialQuery,
  items,
  properties,
  propertiesStatus,
  onRunItem,
  onPickProperty,
  onCloseAutoFocus,
  onOpenLink,
  search,
}: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const idPrefix = useId().replace(/:/g, "");
  const listboxId = `${idPrefix}-listbox`;
  const [query, setQuery] = useState(initialQuery);
  const [pickAction, setPickAction] = useState<PropertyScopedActionId | null>(null);
  const [highlight, setHighlight] = useState(0);
  const picking = pickAction !== null;

  const trimmedQuery = query.trim();
  const global = useGlobalSearch(picking ? "" : query, search);
  const searching = !picking && trimmedQuery.length >= MIN_SEARCH_LENGTH;
  const tokens = useMemo(() => tokenize(query), [query]);

  const localEntries = useMemo(() => {
    if (pickAction !== null) {
      const pickItems: PaletteItem[] = properties.map((p) => ({
        kind: "destination",
        id: `pick:${p.id}`,
        label: p.name,
        keywords: [],
        to: "",
        group: "Properties",
      }));
      return rankLocal(pickItems, query, 50).map((item) => ({
        item,
        group: "Choose a property",
        propertyId: item.id.slice("pick:".length),
      }));
    }
    const source = query.trim() === "" ? emptyQueryItems(items) : items;
    const ranked =
      query.trim() === ""
        ? source.slice()
        : rankLocal(source, query, MAX_LOCAL_ITEMS);
    return groupContiguous(
      ranked.map((item) => ({ item, group: groupOf(item), propertyId: "" })),
    );
  }, [pickAction, properties, items, query]);

  const built = useMemo(() => {
    const out: { row: PaletteRow; entry: Entry }[] = localEntries.map(
      ({ item, group, propertyId }) => ({
        entry: { type: "local", item, propertyId },
        row: {
          key: item.id,
          group,
          label: item.label,
          hint: item.hint,
          disabled:
            item.kind === "action" &&
            isPropertyScopedAction(item.id) &&
            properties.length === 0,
        },
      }),
    );
    if (!searching) return out;
    const seeAllLink = `/search?q=${encodeURIComponent(trimmedQuery)}`;
    let hitCount = 0;
    for (const group of orderedGroups(global.groups)) {
      const label = groupLabel(group.kind);
      const hits = group.hits.slice(0, PALETTE_HITS_PER_GROUP);
      for (const hit of hits) {
        hitCount += 1;
        out.push({
          entry: { type: "link", link: hit.link },
          row: {
            key: `hit:${hit.kind}:${hit.id}`,
            group: label,
            label: hit.title,
            hint: hit.subtitle ?? undefined,
            highlight: tokens,
          },
        });
      }
      if (group.total > hits.length) {
        out.push({
          entry: { type: "link", link: seeAllLink },
          row: {
            key: `see-all:${group.kind}`,
            group: label,
            label: `See all ${group.total} results`,
            seeAll: true,
          },
        });
      }
    }
    if (
      out.length === 0 &&
      hitCount === 0 &&
      (global.status === "loaded" || global.status === "error")
    ) {
      out.push({
        entry: { type: "link", link: seeAllLink },
        row: {
          key: "see-all:none",
          group: "Search",
          label: `See all results for "${trimmedQuery}"`,
          seeAll: true,
        },
      });
    }
    return out;
  }, [localEntries, properties.length, searching, trimmedQuery, global.groups, global.status, tokens]);

  const rows: PaletteRow[] = built.map((b) => b.row);
  const resultCount = rows.filter((row) => !row.seeAll).length;
  const busy = searching && global.status === "loading";

  const activeIndex = rows.length === 0 ? -1 : Math.min(highlight, rows.length - 1);
  const activeId = activeIndex >= 0 ? optionId(idPrefix, activeIndex) : undefined;

  useEffect(() => {
    if (!activeId) return;
    const el = document.getElementById(activeId);
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ block: "nearest" });
    }
  }, [activeId]);

  const countText =
    resultCount === 0
      ? busy
        ? "Searching"
        : "No results"
      : `${resultCount} ${resultCount === 1 ? "result" : "results"}`;

  function runAt(index: number) {
    const built_ = built[index];
    if (!built_ || rows[index].disabled) return;
    const { entry } = built_;
    if (entry.type === "link") {
      // Only same-app paths are followed (Requirement 11.5).
      if (isSafeAppLink(entry.link)) onOpenLink?.(entry.link);
      return;
    }
    if (pickAction !== null) {
      onPickProperty(pickAction, entry.propertyId);
      return;
    }
    const result = onRunItem(entry.item);
    if (result && "pick" in result) {
      setPickAction(result.pick);
      setQuery("");
      setHighlight(0);
      inputRef.current?.focus();
    }
  }

  function leavePicker() {
    setPickAction(null);
    setQuery("");
    setHighlight(0);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    const input = event.currentTarget;
    const empty = input.value === "";
    const atStart = input.selectionStart === 0 && input.selectionEnd === 0;
    const atEnd =
      input.selectionStart === input.value.length &&
      input.selectionEnd === input.value.length;
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp":
        event.preventDefault();
        setHighlight(
          moveHighlight(
            activeIndex < 0 ? (event.key === "ArrowDown" ? -1 : 0) : activeIndex,
            rows.length,
            event.key === "ArrowDown" ? "next" : "prev",
          ),
        );
        break;
      case "Home":
        if (empty || atStart) {
          event.preventDefault();
          if (rows.length > 0) setHighlight(0);
        }
        break;
      case "End":
        if (empty || atEnd) {
          event.preventDefault();
          if (rows.length > 0) setHighlight(rows.length - 1);
        }
        break;
      case "Enter":
        event.preventDefault();
        if (activeIndex >= 0) runAt(activeIndex);
        break;
      case "Backspace":
        if (picking && empty) {
          event.preventDefault();
          leavePicker();
        }
        break;
      default:
    }
  }

  return (
    <Dialog.Content
      data-palette=""
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        inputRef.current?.focus();
      }}
      onCloseAutoFocus={onCloseAutoFocus}
      onEscapeKeyDown={(event) => {
        if (picking) {
          event.preventDefault();
          leavePicker();
        }
      }}
      className="fixed left-1/2 top-[8dvh] z-50 flex max-h-[84dvh] w-[calc(100vw-1rem)] max-w-xl -translate-x-1/2 flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-card focus:outline-none"
    >
      <Dialog.Title className="sr-only">Command palette</Dialog.Title>
      <Dialog.Description className="sr-only">
        Search pages, properties, tax years and actions. Use the arrow keys to
        move and Enter to choose.
      </Dialog.Description>
      <div className="border-b border-border p-2">
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={true}
          aria-controls={listboxId}
          aria-activedescendant={activeId}
          aria-autocomplete="list"
          aria-label={picking ? "Choose a property" : "Search or run a command"}
          autoComplete="off"
          spellCheck={false}
          placeholder={picking ? "Choose a property" : "Search or run a command"}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setHighlight(0);
          }}
          onKeyDown={onKeyDown}
          className={cn(
            "w-full rounded-md border border-border bg-surface px-3 py-2 text-base text-fg placeholder:text-fg-muted",
            FOCUS_RING,
          )}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PaletteList
          rows={rows}
          activeIndex={activeIndex}
          idPrefix={idPrefix}
          listboxId={listboxId}
          busy={busy}
          onHighlight={setHighlight}
          onRun={runAt}
        />
        {resultCount === 0 ? (
          <p className="px-3 py-4 text-sm text-fg-muted">
            {busy ? "Searching…" : "No results"}
          </p>
        ) : null}
        {searching ? (
          <div className="flex min-h-8 items-center gap-2 px-3 pb-2 text-xs text-fg-muted">
            {global.status === "error" ? (
              <div role="alert" className="flex items-center gap-2">
                <span>{SEARCH_ERROR_TEXT}</span>
                <button
                  type="button"
                  onClick={global.retry}
                  className={cn(
                    "rounded-md border border-border px-2 py-1 text-fg",
                    FOCUS_RING,
                  )}
                >
                  Retry
                </button>
              </div>
            ) : busy ? (
              <span>Searching…</span>
            ) : global.truncated ? (
              <span>{TRUNCATION_NOTICE}</span>
            ) : null}
          </div>
        ) : null}
        {!picking && propertiesStatus === "loading" ? (
          <p className="px-3 pb-3 text-xs text-fg-muted">Loading properties…</p>
        ) : null}
        {!picking && propertiesStatus === "error" ? (
          <p className="px-3 pb-3 text-xs text-fg-muted">
            Properties could not be loaded.
          </p>
        ) : null}
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {countText}
      </div>
    </Dialog.Content>
  );
}
