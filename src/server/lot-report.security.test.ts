import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createReportImageBudget,
  fetchImagesAsBase64,
  isAllowedReportImageUrl,
} from "./lot-report";

const ALLOWED_URL = "https://images.copart.com/lot/example.jpg";

describe("report image security", () => {
  beforeEach(() => {
    vi.stubEnv("REPORT_IMAGE_ALLOWED_HOSTS", ".copart.com,.iaai.com");
    vi.stubEnv("REPORT_IMAGE_MAX_BYTES", "102400");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it.each([
    "https://copart.com/image.jpg",
    "https://images.copart.com/image.jpg",
    "https://vis.iaai.com/image.png",
  ])("allows configured HTTPS auction hosts: %s", (url) => {
    expect(isAllowedReportImageUrl(url)).toBe(true);
  });

  it.each([
    "http://images.copart.com/image.jpg",
    "https://evilcopart.com/image.jpg",
    "https://localhost/image.jpg",
    "https://127.0.0.1/image.jpg",
    "https://user:pass@images.copart.com/image.jpg",
    "https://images.copart.com:8443/image.jpg",
    "not-a-url",
  ])("blocks unsafe image URL: %s", (url) => {
    expect(isAllowedReportImageUrl(url)).toBe(false);
  });

  it("downloads a small allowlisted image", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(new Uint8Array([1, 2, 3]), {
          status: 200,
          headers: { "Content-Type": "image/jpeg", "Content-Length": "3" },
        }),
      ),
    );
    const [image] = await fetchImagesAsBase64([ALLOWED_URL]);
    expect(image).toBe("data:image/jpeg;base64,AQID");
    expect(fetch).toHaveBeenCalledWith(
      ALLOWED_URL,
      expect.objectContaining({ redirect: "manual" }),
    );
  });

  it("does not fetch a blocked URL", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const [image] = await fetchImagesAsBase64(["https://169.254.169.254/latest/meta-data"]);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(image).toContain("data:image/svg+xml;base64,");
  });

  it("blocks redirects outside the allowlist", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: { Location: "https://127.0.0.1/internal" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const [image] = await fetchImagesAsBase64([ALLOWED_URL]);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(image).toContain("data:image/svg+xml;base64,");
  });

  it("shares a hard byte budget across all report images", async () => {
    const payload = new Uint8Array(60 * 1024);
    const fetchMock = vi.fn().mockImplementation(
      async () =>
        new Response(payload, {
          status: 200,
          headers: {
            "Content-Type": "image/jpeg",
            "Content-Length": String(payload.byteLength),
          },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const budget = createReportImageBudget(100 * 1024);

    const images = await fetchImagesAsBase64([ALLOWED_URL, ALLOWED_URL], 8, budget);

    expect(images[0]).toMatch(/^data:image\/jpeg;base64,/);
    expect(images[1]).toContain("data:image/svg+xml;base64,");
    expect(budget.remainingBytes).toBe(40 * 1024);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("debits rejected streamed bytes and stops further downloads", async () => {
    const oversizedPayload = new Uint8Array(120 * 1024);
    const fetchMock = vi.fn().mockImplementation(
      async () =>
        new Response(oversizedPayload, {
          status: 200,
          headers: { "Content-Type": "image/jpeg" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const budget = createReportImageBudget(100 * 1024);

    const images = await fetchImagesAsBase64([ALLOWED_URL, ALLOWED_URL], 8, budget);

    expect(images).toHaveLength(2);
    expect(images.every((image) => image.includes("data:image/svg+xml;base64,"))).toBe(true);
    expect(budget.remainingBytes).toBe(0);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("caps redirect and request attempts across the whole report", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: { Location: ALLOWED_URL },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const budget = createReportImageBudget();
    budget.remainingRequests = 1;

    const [image] = await fetchImagesAsBase64([ALLOWED_URL], 8, budget);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(budget.remainingRequests).toBe(0);
    expect(image).toContain("data:image/svg+xml;base64,");
  });

  it("does not start requests after the report-wide deadline", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const budget = createReportImageBudget(100 * 1024, Date.now() - 30_001);

    const [image] = await fetchImagesAsBase64([ALLOWED_URL], 8, budget);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(image).toContain("data:image/svg+xml;base64,");
  });

  it("rejects non-images and oversized bodies", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response("not an image", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(new Uint8Array(102_401), {
          status: 200,
          headers: { "Content-Type": "image/jpeg" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const images = await fetchImagesAsBase64([ALLOWED_URL, ALLOWED_URL]);
    expect(images).toHaveLength(2);
    expect(images.every((image) => image.includes("data:image/svg+xml;base64,"))).toBe(true);
  });
});
