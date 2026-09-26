import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProfilePage from "./ProfilePage";
import type { UserProfile } from "../lib/auth";

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

const SUB = "9f8c1a2b-3d4e-5f60-7a81-92b3c4d5e6f7";

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

    render(<ProfilePage />);

    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
  });

  it("does not display the raw Cognito sub anywhere on the page", () => {
    getUserProfile.mockReturnValue({
      sub: SUB,
      email: "owner@example.com",
      displayName: "owner@example.com",
    });

    render(<ProfilePage />);

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

    render(<ProfilePage />);

    expect(screen.getByText(/managed by the identity provider/i)).toBeInTheDocument();
    expect(screen.getByText(/Amazon\s+Cognito/i)).toBeInTheDocument();
  });

  it("still renders no raw identifier when the profile is unavailable", () => {
    getUserProfile.mockReturnValue(null);

    render(<ProfilePage />);

    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.queryByText("User ID")).not.toBeInTheDocument();
    expect(screen.queryByText(SUB)).not.toBeInTheDocument();
  });
});
