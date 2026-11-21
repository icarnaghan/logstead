import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import {
  NavigationGuardProvider,
  useGuardedNavigate,
  useRegisterDirty,
} from "./navigationGuard";

function Where() {
  return <p data-testid="path">{useLocation().pathname}</p>;
}
function Probe({ dirty }: { dirty: boolean }) {
  useRegisterDirty("form", dirty);
  const { go } = useGuardedNavigate();
  return <button onClick={() => go("/next")}>Go</button>;
}
function setup(dirty: boolean) {
  render(
    <MemoryRouter initialEntries={["/start"]}>
      <NavigationGuardProvider>
        <Probe dirty={dirty} />
        <Where />
      </NavigationGuardProvider>
    </MemoryRouter>,
  );
}

describe("navigationGuard", () => {
  it("navigates directly when clean", async () => {
    setup(false);
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(screen.getByTestId("path")).toHaveTextContent("/next");
    expect(screen.queryByText("Discard changes?")).toBeNull();
  });

  it("asks first when dirty and Keep editing stays", async () => {
    setup(true);
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(screen.getByText("Discard changes?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByTestId("path")).toHaveTextContent("/start");
    expect(screen.queryByText("Discard changes?")).toBeNull();
  });

  it("Discard navigates", async () => {
    setup(true);
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByTestId("path")).toHaveTextContent("/next");
  });
});
