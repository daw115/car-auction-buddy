// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { PasswordGate } from "./PasswordGate";
import { siteUserLogout, siteUserSession } from "@/functions/site-auth.functions";

vi.mock("@/functions/site-auth.functions", () => ({
  siteUserDeletePassword: vi.fn(),
  siteUserHasPassword: vi.fn(),
  siteUserLogin: vi.fn(),
  siteUserLogout: vi.fn(),
  siteUserSession: vi.fn(),
  siteUserSetPassword: vi.fn(),
}));

// Node >= 22 ships a built-in `localStorage` global that stays `undefined` unless the process
// is started with --localstorage-file. Vitest's jsdom environment only copies window properties
// that do not already exist on globalThis, so jsdom's real Storage is skipped and `localStorage`
// resolves to that undefined stub. Install a spec-shaped in-memory Storage when that happens
// (same approach as src/lib/scrape-job-storage.test.ts).
function createMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    key: (index: number) => [...store.keys()][index] ?? null,
    getItem: (key: string) => store.get(String(key)) ?? null,
    setItem: (key: string, value: string) => {
      store.set(String(key), String(value));
    },
    removeItem: (key: string) => {
      store.delete(String(key));
    },
    clear: () => store.clear(),
  };
}

if (!globalThis.localStorage) {
  Object.defineProperty(globalThis, "localStorage", {
    value: createMemoryStorage(),
    configurable: true,
    writable: true,
  });
}

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
