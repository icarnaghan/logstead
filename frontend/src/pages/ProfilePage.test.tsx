import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import ProfilePage from "./ProfilePage";
import { ToastProvider } from "../components/ui";
import type { UserProfile } from "../lib/auth";
import type {
  BackupDocument,
  ClearSummary,
  RestoreSummary,
} from "../api/backup";
import sampleBackup from "../data/sample-backup.json";

/**
 * ProfilePage now hosts the Backup & restore section, which calls
 * `useToast()`. That hook throws outside a `ToastProvider`, so render the page
 * inside one. The toast APIs are portalled and do not affect the assertions
 * below.
 */
function renderProfilePage() {
  return render(
    <ToastProvider>
      <ProfilePage />
    </ToastProvider>,
  );
}

/**
 * Component tests for the profile page (task 7.6, Requirement 3.2).
 *
 * The page must present human-readable account information (the email) and
 * MUST NOT surface the Cognito `sub` raw identifier as user-facing content.
 * `getUserProfile` is mocked so the tests exercise the rendering behaviour
 * without any token/JWT plumbing.
 */

const { getUserProfile } = vi.hoisted(() => ({
  getUserProfile: vi.fn<() => UserProfile | null>(),
}));

vi.mock("../lib/auth", () => ({ getUserProfile }));

// The backup API module is mocked so the four flows exercise the page's
// behaviour (download/restore/clear/load-sample) without any network access,
// matching how sibling page tests isolate their API layer. `ApiError` is
// preserved as a real class so `err instanceof ApiError` checks still work.
const { fetchBackup, restoreBackup, clearData } = vi.hoisted(() => ({
  fetchBackup: vi.fn<() => Promise<BackupDocument>>(),
  restoreBackup: vi.fn<(doc: BackupDocument) => Promise<RestoreSummary>>(),
  clearData: vi.fn<() => Promise<ClearSummary>>(),
}));

vi.mock("../api/backup", async () => {
  const actual =
    await vi.importActual<typeof import("../api/backup")>("../api/backup");
  return { ...actual, fetchBackup, restoreBackup, clearData };
});

const SUB = "9f8c1a2b-3d4e-5f60-7a81-92b3c4d5e6f7";

/** A minimal, valid backup document used by the download/restore flows. */
function makeBackup(): BackupDocument {
  return {
    schema_version: "1",
    exported_at: "2025-02-14T10:30:00+00:00",
    properties: [],
  };
}

const RESTORE_SUMMARY: RestoreSummary = {
  properties: 1,
  transactions: 2,
  assets: 1,
  usage_years: 1,
};

const CLEAR_SUMMARY: ClearSummary = {
  properties: 0,
  transactions: 0,
  assets: 0,
  photos: 0,
  receipts: 0,
  failed_s3_keys: [],
};

/**
 * Build a `File` whose `.text()` resolves to `contents`. jsdom's `File.text()`
 * is not reliably implemented under the test environment, so it is provided
 * explicitly to make the page's `await file.text()` deterministic.
 */
function jsonFile(contents: string, name = "backup.json"): File {
  const file = new File([contents], name, { type: "application/json" });
  Object.defineProperty(file, "text", {
    value: () => Promise.resolve(contents),
    configurable: true,
  });
  return file;
}

beforeEach(() => {
  getUserProfile.mockReturnValue({
    sub: SUB,
    email: "owner@example.com",
    displayName: "owner@example.com",
  });
  fetchBackup.mockResolvedValue(makeBackup());
  restoreBackup.mockResolvedValue(RESTORE_SUMMARY);
  clearData.mockResolvedValue(CLEAR_SUMMARY);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ProfilePage — no raw Cognito identifier (Req 3.2)", () => {
  it("shows the human-readable email in the account section", () => {
    getUserProfile.mockReturnValue({
      sub: SUB,
      email: "owner@example.com",
      displayName: "owner@example.com",
    });

    renderProfilePage();

    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
  });

  it("does not display the raw Cognito sub anywhere on the page", () => {
    getUserProfile.mockReturnValue({
      sub: SUB,
      email: "owner@example.com",
      displayName: "owner@example.com",
    });

    renderProfilePage();

    expect(screen.queryByText("User ID")).not.toBeInTheDocument();
    expect(screen.queryByText(SUB)).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp(SUB))).not.toBeInTheDocument();
  });

  it("keeps the note that sign-in is managed by Amazon Cognito", () => {
    getUserProfile.mockReturnValue({
      sub: SUB,
      email: "owner@example.com",
      displayName: "owner@example.com",
    });

    renderProfilePage();

    expect(screen.getByText(/managed by the identity provider/i)).toBeInTheDocument();
    expect(screen.getByText(/Amazon\s+Cognito/i)).toBeInTheDocument();
  });

  it("still renders no raw identifier when the profile is unavailable", () => {
    getUserProfile.mockReturnValue(null);

    renderProfilePage();

    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.queryByText("User ID")).not.toBeInTheDocument();
    expect(screen.queryByText(SUB)).not.toBeInTheDocument();
  });
});

/**
 * Behavioural tests for the Backup & restore section (task 12.2,
 * Requirements 1.12, 6.1, 6.2, 9.1, 9.2, 10.5, 10.6).
 *
 * The `ConfirmDialog` is portalled by Radix, so renders are wrapped in
 * `ToastProvider` (via `renderProfilePage`) and dialog controls are queried by
 * their accessible role. Success/error feedback surfaces as toast titles,
 * which render as plain text.
 */

describe("ProfilePage — Backup & restore: Download (Req 1.12)", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.spyOn>;
  let blobSpy: ReturnType<typeof vi.spyOn>;
  let downloadName: string | undefined;
  let captured: { type: string; content: string }[];

  beforeEach(() => {
    captured = [];
    downloadName = undefined;
    const RealBlob = globalThis.Blob;
    // jsdom's Blob does not expose a usable .text(); record the parts + MIME
    // type at construction so the serialized download content is assertable.
    blobSpy = vi
      .spyOn(globalThis, "Blob")
      .mockImplementation((parts?: BlobPart[], options?: BlobPropertyBag) => {
        captured.push({
          type: options?.type ?? "",
          content: (parts ?? []).map((part) => String(part)).join(""),
        });
        return new RealBlob(parts, options);
      }) as unknown as ReturnType<typeof vi.spyOn>;

    createObjectURL = vi.fn(() => "blob:mock-url");
    revokeObjectURL = vi.fn();
    // jsdom does not implement the object-URL APIs.
    (URL as unknown as { createObjectURL: unknown }).createObjectURL =
      createObjectURL;
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL =
      revokeObjectURL;

    // Capture the anchor's download filename and swallow the click so jsdom
    // does not emit a "navigation not implemented" warning.
    clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloadName = this.download;
      });
  });

  afterEach(() => {
    clickSpy.mockRestore();
    blobSpy.mockRestore();
  });

  it("fetches the backup and downloads it as logstead-backup-<local date>.json", async () => {
    const user = userEvent.setup();
    renderProfilePage();

    await user.click(
      screen.getByRole("button", { name: /^download backup$/i }),
    );

    // A success toast confirms the flow completed.
    expect(await screen.findByText("Backup downloaded")).toBeInTheDocument();

    // The document was fetched from the API layer.
    expect(fetchBackup).toHaveBeenCalledTimes(1);

    // A JSON Blob was created and the object-URL lifecycle ran.
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");

    const [entry] = captured;
    expect(entry.type).toBe("application/json");
    // Serialized content is the fetched document.
    expect(JSON.parse(entry.content)).toEqual(makeBackup());

    // Filename carries the local date as YYYY-MM-DD.
    const now = new Date();
    const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(
      2,
      "0",
    )}-${String(now.getDate()).padStart(2, "0")}`;
    expect(downloadName).toBe(`logstead-backup-${stamp}.json`);
  });

  it("shows an error toast and does not download when the fetch fails", async () => {
    const user = userEvent.setup();
    fetchBackup.mockRejectedValueOnce(new Error("network"));
    renderProfilePage();

    await user.click(
      screen.getByRole("button", { name: /^download backup$/i }),
    );

    expect(
      await screen.findByText("Could not download the backup"),
    ).toBeInTheDocument();
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(clickSpy).not.toHaveBeenCalled();
  });
});

describe("ProfilePage — Backup & restore: Restore from file (Req 6.1, 6.2)", () => {
  /** Grab the hidden file input the "Restore from file" button proxies to. */
  function fileInput(): HTMLInputElement {
    // The only file input on the page is the restore uploader.
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement | null;
    if (!input) throw new Error("file input not found");
    return input;
  }

  it("opens the confirm dialog when a valid JSON file is selected", async () => {
    const user = userEvent.setup();
    renderProfilePage();

    await user.upload(fileInput(), jsonFile(JSON.stringify(makeBackup())));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("heading", { name: /restore this backup\?/i }),
    ).toBeInTheDocument();
    // No request until the user confirms.
    expect(restoreBackup).not.toHaveBeenCalled();
  });

  it("confirming POSTs the parsed document and shows a success toast", async () => {
    const user = userEvent.setup();
    const doc = makeBackup();
    renderProfilePage();

    await user.upload(fileInput(), jsonFile(JSON.stringify(doc)));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^restore$/i }));

    expect(await screen.findByText("Backup restored")).toBeInTheDocument();
    expect(restoreBackup).toHaveBeenCalledTimes(1);
    expect(restoreBackup).toHaveBeenCalledWith(doc);
  });

  it("cancelling the restore dialog makes no request", async () => {
    const user = userEvent.setup();
    renderProfilePage();

    await user.upload(fileInput(), jsonFile(JSON.stringify(makeBackup())));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    // Dialog closes and nothing is sent.
    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(restoreBackup).not.toHaveBeenCalled();
  });

  it("shows a parse-error toast and makes no request for a malformed file", async () => {
    const user = userEvent.setup();
    renderProfilePage();

    await user.upload(fileInput(), jsonFile("this is not json{"));

    expect(
      await screen.findByText("Could not read the backup file"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(restoreBackup).not.toHaveBeenCalled();
  });
});

describe("ProfilePage — Backup & restore: Clear all data (Req 9.1, 9.2)", () => {
  it("confirming clears the data and shows a success toast", async () => {
    const user = userEvent.setup();
    renderProfilePage();

    await user.click(screen.getByRole("button", { name: /^clear all data$/i }));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("heading", { name: /clear all data\?/i }),
    ).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: /^clear all data…?$/i }),
    );

    expect(await screen.findByText("All data cleared")).toBeInTheDocument();
    expect(clearData).toHaveBeenCalledTimes(1);
  });

  it("cancelling the clear dialog makes no request", async () => {
    const user = userEvent.setup();
    renderProfilePage();

    await user.click(screen.getByRole("button", { name: /^clear all data$/i }));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(clearData).not.toHaveBeenCalled();
  });
});

describe("ProfilePage — Backup & restore: Load sample data (Req 10.5, 10.6)", () => {
  it("opens the restore dialog and POSTs the bundled sample fixture on confirm", async () => {
    const user = userEvent.setup();
    renderProfilePage();

    await user.click(
      screen.getByRole("button", { name: /^load sample data$/i }),
    );

    // Same destructive restore confirmation is reused.
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("heading", { name: /restore this backup\?/i }),
    ).toBeInTheDocument();
    expect(restoreBackup).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: /^restore$/i }));

    expect(await screen.findByText("Backup restored")).toBeInTheDocument();
    expect(restoreBackup).toHaveBeenCalledTimes(1);
    // The document sent is the bundled sample fixture.
    expect(restoreBackup).toHaveBeenCalledWith(sampleBackup);
  });
});

describe("ProfilePage — Backup & restore: accessibility (axe)", () => {
  it("has no axe violations for the rendered page", async () => {
    const { container } = renderProfilePage();

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("has no axe violations while a restore confirm dialog is open", async () => {
    const user = userEvent.setup();
    const { baseElement } = renderProfilePage();

    await user.click(
      screen.getByRole("button", { name: /^load sample data$/i }),
    );
    await screen.findByRole("dialog");

    // The dialog is portalled outside `container`; axe over `baseElement`
    // covers the portalled dialog content too.
    const results = await axe(baseElement, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
