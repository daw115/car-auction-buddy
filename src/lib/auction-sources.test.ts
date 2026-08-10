import { describe, expect, it } from "vitest";
import {
  auctionSourceCapabilitiesPayloadSchema,
  auctionSourceSchema,
  DEFAULT_AUCTION_SOURCES,
  getUnavailableAuctionSources,
  normalizeAuctionSources,
  type AuctionSourceCapabilities,
} from "./auction-sources";

describe("auction sources", () => {
  it("accepts Manheim as a supported source", () => {
    expect(auctionSourceSchema.parse("manheim")).toBe("manheim");
  });

  it("accepts Manheim as a live source and rejects retired modes", () => {
    const payload = {
      checkedAt: "2026-07-19T00:00:00.000Z",
      sources: {
        copart: { available: true as const, mode: "live" as const },
        iaai: { available: true as const, mode: "live" as const },
        manheim: { available: true as const, mode: "live" as const },
      },
    };

    expect(auctionSourceCapabilitiesPayloadSchema.safeParse(payload).success).toBe(true);
    expect(
      auctionSourceCapabilitiesPayloadSchema.safeParse({
        ...payload,
        sources: {
          ...payload.sources,
          manheim: { available: true, mode: "official_api" },
        },
      }).success,
    ).toBe(false);
  });

  it("keeps Manheim opt-in", () => {
    expect(DEFAULT_AUCTION_SOURCES).toEqual(["copart", "iaai"]);
    expect(DEFAULT_AUCTION_SOURCES).not.toContain("manheim");
  });

  it("normalizes known sources, preserves Manheim and removes duplicates", () => {
    expect(normalizeAuctionSources(["manheim", "copart", "manheim", "unknown"])).toEqual([
      "manheim",
      "copart",
    ]);
  });

  it("blocks Manheim until backend capabilities confirm availability", () => {
    expect(getUnavailableAuctionSources(["copart", "manheim"], undefined)).toEqual(["manheim"]);

    const capabilities: AuctionSourceCapabilities = {
      checkedAt: "2026-07-19T00:00:00.000Z",
      sources: {
        copart: { available: true, mode: "live" },
        iaai: { available: true, mode: "live" },
        manheim: { available: true, mode: "live" },
      },
    };

    expect(getUnavailableAuctionSources(["manheim"], capabilities)).toEqual([]);

    const sessionMissing: AuctionSourceCapabilities = {
      ...capabilities,
      sources: {
        ...capabilities.sources,
        manheim: {
          available: false,
          mode: "unavailable",
          reason: "manheim_session_not_configured",
        },
      },
    };
    expect(getUnavailableAuctionSources(["manheim"], sessionMissing)).toEqual(["manheim"]);
  });
});
