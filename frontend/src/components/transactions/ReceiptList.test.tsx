import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import type {
  AttachReceiptResult,
  ReceiptDocument,
  TransactionsApi,
} from "../../api/transactions";
import { ReceiptList } from "./ReceiptList";

/**
 * Component tests for the per-transaction receipts UI in isolation (task 22.3).
 *
 * The transactions API is fully injected (no network): the attach flow requests
 * a pre-signed URL, PUTs the bytes, then calls `onChanged`; the list renders
 * download links; delete removes a receipt; and an attach failure surfaces an
 * error message.
 *
 * Validates: Requirement 5.8
 */

const PROPERTY_ID = "p1";
const TRANSACTION_ID = "t1";

const RECEIPTS: ReceiptDocument[] = [
  {
    id: "doc-1",
    filename: "invoice.pdf",
    content_type: "application/pdf",
    download_url: "https://s3.example/invoice.pdf?sig=abc",
  },
  {
    id: "doc-2",
    filename: "photo.jpg",
    content_type: "image/jpeg",
  },
];

/** A minimal fake of the {@link TransactionsApi} covering the receipt methods. */
function makeApi(overrides: Partial<TransactionsApi> = {}): TransactionsApi {
  const attachResult: AttachReceiptResult = {
    upload_url: "https://s3.example/upload?sig=put",
    document: {
      id: "doc-new",
      filename: "new.pdf",
      content_type: "application/pdf",
    },
  };
  return {
    attachReceipt: vi.fn(async () => attachResult),
    uploadToPresignedUrl: vi.fn(async () => {}),
    deleteReceipt: vi.fn(async () => {}),
    ...overrides,
  } as unknown as TransactionsApi;
}

function pdf(name = "new.pdf"): File {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

describe("ReceiptList", () => {
  it("renders existing receipts with download links", () => {
    render(
      <ReceiptList
        api={makeApi()}
        propertyId={PROPERTY_ID}
        transactionId={TRANSACTION_ID}
        receipts={RECEIPTS}
        onChanged={vi.fn()}
      />,
    );

    const link = screen.getByRole("link", { name: /invoice\.pdf/i });
    expect(link).toHaveAttribute("href", "https://s3.example/invoice.pdf?sig=abc");
    // A receipt without a download_url renders as plain text, not a link.
    expect(
      screen.queryByRole("link", { name: /photo\.jpg/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("photo.jpg")).toBeInTheDocument();
  });

  it("shows an empty-state message when there are no receipts", () => {
    render(
      <ReceiptList
        api={makeApi()}
        propertyId={PROPERTY_ID}
        transactionId={TRANSACTION_ID}
        receipts={[]}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByText(/no documents attached/i)).toBeInTheDocument();
  });

  it("requests a pre-signed URL, PUTs the bytes, then calls onChanged", async () => {
    const api = makeApi();
    const onChanged = vi.fn();
    const user = userEvent.setup();
    render(
      <ReceiptList
        api={api}
        propertyId={PROPERTY_ID}
        transactionId={TRANSACTION_ID}
        receipts={[]}
        onChanged={onChanged}
      />,
    );

    const file = pdf();
    await user.upload(screen.getByLabelText(/attach a document/i), file);

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(api.attachReceipt).toHaveBeenCalledWith(
      PROPERTY_ID,
      TRANSACTION_ID,
      "new.pdf",
      "application/pdf",
    );
    expect(api.uploadToPresignedUrl).toHaveBeenCalledWith(
      "https://s3.example/upload?sig=put",
      file,
      "application/pdf",
    );
    // The two-step flow must request the URL before PUTing the bytes.
    const attachOrder = (api.attachReceipt as ReturnType<typeof vi.fn>).mock
      .invocationCallOrder[0];
    const putOrder = (api.uploadToPresignedUrl as ReturnType<typeof vi.fn>).mock
      .invocationCallOrder[0];
    expect(attachOrder).toBeLessThan(putOrder);
  });

  it("deletes a receipt and refreshes the list", async () => {
    const api = makeApi();
    const onChanged = vi.fn();
    const user = userEvent.setup();
    render(
      <ReceiptList
        api={api}
        propertyId={PROPERTY_ID}
        transactionId={TRANSACTION_ID}
        receipts={RECEIPTS}
        onChanged={onChanged}
      />,
    );

    const [firstDelete] = screen.getAllByRole("button", { name: /delete/i });
    await user.click(firstDelete);

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(api.deleteReceipt).toHaveBeenCalledWith(
      PROPERTY_ID,
      TRANSACTION_ID,
      "doc-1",
    );
  });

  it("shows an error when the attach flow fails and does not call onChanged", async () => {
    const api = makeApi({
      attachReceipt: vi.fn(async () => {
        throw new Error("network down");
      }),
    });
    const onChanged = vi.fn();
    const user = userEvent.setup();
    render(
      <ReceiptList
        api={api}
        propertyId={PROPERTY_ID}
        transactionId={TRANSACTION_ID}
        receipts={[]}
        onChanged={onChanged}
      />,
    );

    await user.upload(screen.getByLabelText(/attach a document/i), pdf());

    expect(
      await screen.findByText(/could not attach the document/i),
    ).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("has no automated accessibility violations with receipts listed", async () => {
    const { container } = render(
      <ReceiptList
        api={makeApi()}
        propertyId={PROPERTY_ID}
        transactionId={TRANSACTION_ID}
        receipts={RECEIPTS}
        onChanged={vi.fn()}
      />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
