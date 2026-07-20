import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deleteCookie, getCookie, setCookie } from "@tanstack/react-start/server";
import {
  clearSiteSession,
  createSiteSessionToken,
  getSiteSession,
  requireSiteSession,
  setSiteSession,
  verifySiteSessionToken,
} from "./site-session.server";

vi.mock("@tanstack/react-start/server", () => ({
  deleteCookie: vi.fn(),
  getCookie: vi.fn(),
  setCookie: vi.fn(),
}));

const SECRET = "a-secure-session-secret-with-at-least-32-characters";
const NOW = Date.UTC(2026, 6, 15, 12, 0, 0);

describe("site session tokens", () => {
  beforeEach(() => {
    vi.stubEnv("SITE_SESSION_SECRET", SECRET);
    vi.stubEnv("SITE_SESSION_TTL_SECONDS", "3600");
    vi.stubEnv("NODE_ENV", "production");
    vi.mocked(getCookie).mockReset();
    vi.mocked(setCookie).mockReset();
    vi.mocked(deleteCookie).mockReset();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("accepts a valid signed token", () => {
    const token = createSiteSessionToken("Dawid", SECRET, NOW, 3600);
    expect(verifySiteSessionToken(token, SECRET, NOW + 1000)).toMatchObject({
      v: 1,
      sub: "Dawid",
    });
  });

  it.each([
    ["tampered payload", (token: string) => `x${token.slice(1)}`],
    ["tampered signature", (token: string) => `${token.slice(0, -1)}x`],
    ["malformed token", () => "not-a-token"],
  ])("rejects %s", (_label, mutate) => {
    const token = createSiteSessionToken("Pawel", SECRET, NOW, 3600);
    expect(verifySiteSessionToken(mutate(token), SECRET, NOW)).toBeNull();
  });

  it("rejects a token signed with another secret", () => {
    const token = createSiteSessionToken("Pawel", SECRET, NOW, 3600);
    expect(
      verifySiteSessionToken(
        token,
        "another-secure-session-secret-with-at-least-32-characters",
        NOW,
      ),
    ).toBeNull();
  });

  it("rejects expired and far-future tokens", () => {
    const expired = createSiteSessionToken("Pawel", SECRET, NOW, 60);
    const future = createSiteSessionToken("Pawel", SECRET, NOW + 120_000, 3600);
    expect(verifySiteSessionToken(expired, SECRET, NOW + 61_000)).toBeNull();
    expect(verifySiteSessionToken(future, SECRET, NOW)).toBeNull();
  });

  it("sets an HttpOnly, secure, same-site cookie", () => {
    setSiteSession("Dawid");
    expect(setCookie).toHaveBeenCalledOnce();
    const [name, token, options] = vi.mocked(setCookie).mock.calls[0]!;
    expect(name).toBe("car_auction_session");
    expect(verifySiteSessionToken(token, SECRET)).toMatchObject({ sub: "Dawid" });
    expect(options).toMatchObject({
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      maxAge: 3600,
    });
  });

  it("reads a valid cookie and rejects an invalid cookie", () => {
    const token = createSiteSessionToken("Pawel", SECRET);
    vi.mocked(getCookie).mockReturnValueOnce(token).mockReturnValueOnce("invalid");
    expect(getSiteSession()).toMatchObject({ sub: "Pawel" });
    expect(getSiteSession()).toBeNull();
  });

  it("fails closed when a session is missing", () => {
    vi.mocked(getCookie).mockReturnValue(undefined);
    try {
      requireSiteSession();
      throw new Error("expected requireSiteSession to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(Response);
      expect((error as Response).status).toBe(401);
    }
  });

  it("clears the server session cookie", () => {
    clearSiteSession();
    expect(deleteCookie).toHaveBeenCalledWith(
      "car_auction_session",
      expect.objectContaining({ maxAge: 0, httpOnly: true, path: "/" }),
    );
  });
});
