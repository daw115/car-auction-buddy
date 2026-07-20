// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { PasswordGate } from "./PasswordGate";
import { siteUserLogout, siteUserSession } from "@/functions/site-auth.functions";

vi.mock("@/functions/site-auth.functions", () => ({
  siteUserHasPassword: vi.fn(),
  siteUserLogin: vi.fn(),
  siteUserLogout: vi.fn(),
  siteUserSession: vi.fn(),
  siteUserSetPassword: vi.fn(),
}));

describe("PasswordGate server session bootstrap", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(siteUserLogout).mockResolvedValue({ ok: true });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("does not trust a stale localStorage unlock without a server session", async () => {
    localStorage.setItem("site_unlocked_user_v1", "Dawid");
    localStorage.setItem("site_current_user_v1", "Dawid");
    localStorage.setItem("site_last_active_v1", String(Date.now()));
    vi.mocked(siteUserSession).mockResolvedValue({
      authenticated: false,
      username: null,
    });

    render(
      <PasswordGate>
        <div>Chroniona treść</div>
      </PasswordGate>,
    );

    expect(await screen.findByText("Kim jesteś?")).toBeInTheDocument();
    expect(screen.queryByText("Chroniona treść")).not.toBeInTheDocument();
    expect(localStorage.getItem("site_unlocked_user_v1")).toBeNull();
    expect(localStorage.getItem("site_current_user_v1")).toBeNull();
  });

  it("unlocks only after the signed server session is confirmed", async () => {
    vi.mocked(siteUserSession).mockResolvedValue({
      authenticated: true,
      username: "Pawel",
    });

    render(
      <PasswordGate>
        <div>Chroniona treść</div>
      </PasswordGate>,
    );

    expect(await screen.findByText("Chroniona treść")).toBeInTheDocument();
    expect(localStorage.getItem("site_current_user_v1")).toBe("Pawel");
  });

  it("clears local state and the HttpOnly session on logout", async () => {
    vi.mocked(siteUserSession).mockResolvedValue({
      authenticated: true,
      username: "Pawel",
    });
    const user = userEvent.setup();

    render(
      <PasswordGate>
        <div>Chroniona treść</div>
      </PasswordGate>,
    );

    await screen.findByText("Chroniona treść");
    await user.click(screen.getByTitle("Wyloguj"));

    await waitFor(() => expect(siteUserLogout).toHaveBeenCalledOnce());
    expect(await screen.findByText("Kim jesteś?")).toBeInTheDocument();
    expect(localStorage.getItem("site_current_user_v1")).toBeNull();
  });
});
