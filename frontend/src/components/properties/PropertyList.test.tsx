import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { PropertyList } from "./PropertyList";
import { ApiError, type Property } from "../../api/properties";
import type { PhotoWithUrl } from "../../api/photos";

/**
 * Component tests for the properties photo-tile grid (Requirements 2.3, 2.6, 2.7).
 */

const properties: Property[] = [
  {
    id: "p1",
    user_id: "u1",
    name: "Maple Duplex",
    address_text: "1 Maple St, Springfield",
    property_type: "duplex",
  },
  {
    id: "p2",
    user_id: "u1",
    name: "Oak House",
    address_text: "2 Oak Ave, Shelbyville",
    property_type: null,
  },
];

function renderList(
  overrides: Partial<React.ComponentProps<typeof PropertyList>> = {},
) {
  const onDeleted = vi.fn();
  render(
    <MemoryRouter>
      <PropertyList
        properties={properties}
        onDeleted={onDeleted}
        loadPhotos={async () => []}
        {...overrides}
      />
    </MemoryRouter>,
  );
  return { onDeleted };
}

describe("PropertyList", () => {
  it("renders each property as a card with name, address, and a dashboard link", () => {
    renderList();

    // The property name links to the property dashboard.
    expect(screen.getByRole("link", { name: "Maple Duplex" })).toHaveAttribute(
      "href",
      "/properties/p1",
    );
    expect(screen.getByText("1 Maple St, Springfield")).toBeInTheDocument();
    expect(screen.getByText("2 Oak Ave, Shelbyville")).toBeInTheDocument();

    // Each card has a Dashboard action linking to /properties/:id.
    const dashboardLinks = screen.getAllByRole("link", { name: "Dashboard" });
    expect(dashboardLinks).toHaveLength(2);
    expect(dashboardLinks[0]).toHaveAttribute("href", "/properties/p1");
  });

  it("shows the first photo when one exists and a placeholder otherwise", async () => {
    const photos: Record<string, PhotoWithUrl[]> = {
      p1: [
        {
          photo: {
            id: "ph1",
            property_id: "p1",
            s3_key: "k",
            content_type: "image/jpeg",
            original_filename: "front.jpg",
            uploaded_at: null,
          },
          display_url: "https://s3.example/front.jpg",
        },
      ],
      p2: [],
    };
    renderList({ loadPhotos: async (id) => photos[id] ?? [] });

    const img = await screen.findByRole("img", { name: /photo of maple duplex/i });
    expect(img).toHaveAttribute("src", "https://s3.example/front.jpg");
    // Oak House has no photo, so no image is rendered for it.
    expect(
      screen.queryByRole("img", { name: /photo of oak house/i }),
    ).not.toBeInTheDocument();
  });

  it("deletes a property from the More menu and notifies the parent on success", async () => {
    const user = userEvent.setup();
    const remove = vi.fn().mockResolvedValue(undefined);
    const { onDeleted } = renderList({ remove });

    await user.click(
      screen.getByRole("button", { name: /more actions for maple duplex/i }),
    );
    await user.click(
      await screen.findByRole("menuitem", { name: /delete maple duplex/i }),
    );

    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("p1"));
    expect(remove).toHaveBeenCalledWith("p1");
  });

  it("surfaces a 409 conflict message inline and does not remove the card", async () => {
    const user = userEvent.setup();
    const remove = vi
      .fn()
      .mockRejectedValue(
        new ApiError(409, "Remove associated transactions and assets first.", {
          error: "conflict",
        }),
      );
    const { onDeleted } = renderList({ remove });

    await user.click(
      screen.getByRole("button", { name: /more actions for oak house/i }),
    );
    await user.click(
      await screen.findByRole("menuitem", { name: /delete oak house/i }),
    );

    expect(
      await screen.findByText(/remove associated transactions and assets first/i),
    ).toBeInTheDocument();
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
