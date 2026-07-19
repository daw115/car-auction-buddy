import { z } from "zod";

export const AUCTION_SOURCE_IDS = ["copart", "iaai", "manheim"] as const;

export const auctionSourceSchema = z.enum(AUCTION_SOURCE_IDS);

export type AuctionSource = z.infer<typeof auctionSourceSchema>;

export const AUCTION_SOURCES: ReadonlyArray<{
  id: AuctionSource;
  label: string;
  description: string;
}> = [
  { id: "copart", label: "Copart", description: "Aukcje Copart" },
  { id: "iaai", label: "IAAI", description: "Aukcje IAAI" },
  {
    id: "manheim",
    label: "Manheim",
    description: "Marketplace Manheim (Simulcast, OVE i Manheim Express)",
  },
];

export const DEFAULT_AUCTION_SOURCES: AuctionSource[] = ["copart", "iaai"];

export function isAuctionSource(value: string): value is AuctionSource {
  return auctionSourceSchema.safeParse(value).success;
}

export function normalizeAuctionSources(
  values: readonly string[] | null | undefined,
): AuctionSource[] {
  if (values == null) return [...DEFAULT_AUCTION_SOURCES];
  return Array.from(new Set(values.filter(isAuctionSource)));
}
