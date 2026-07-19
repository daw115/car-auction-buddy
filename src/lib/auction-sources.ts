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

export type AuctionSourceMode = "live" | "official_api" | "unavailable";

export type AuctionSourceCapability = {
  available: boolean;
  mode: AuctionSourceMode;
  reason?: string;
};

export type AuctionSourceCapabilities = {
  checkedAt: string;
  sources: Record<AuctionSource, AuctionSourceCapability>;
};

const capabilityReasonSchema = z.string().max(200).optional();
const unavailableSourceCapabilitySchema = z.object({
  available: z.literal(false),
  mode: z.literal("unavailable"),
  reason: capabilityReasonSchema,
});
const liveSourceCapabilitySchema = z.discriminatedUnion("available", [
  z.object({
    available: z.literal(true),
    mode: z.literal("live"),
    reason: capabilityReasonSchema,
  }),
  unavailableSourceCapabilitySchema,
]);
const manheimSourceCapabilitySchema = z.discriminatedUnion("available", [
  z.object({
    available: z.literal(true),
    mode: z.literal("official_api"),
    reason: capabilityReasonSchema,
  }),
  unavailableSourceCapabilitySchema,
]);

export const auctionSourceCapabilitiesPayloadSchema = z.object({
  checkedAt: z.string().optional(),
  sources: z.object({
    copart: liveSourceCapabilitySchema,
    iaai: liveSourceCapabilitySchema,
    manheim: manheimSourceCapabilitySchema,
  }),
});

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

export function isAuctionSourceCapabilityAvailable(
  source: AuctionSource,
  capability: AuctionSourceCapability | null | undefined,
): boolean {
  if (!capability?.available || capability.mode === "unavailable") return false;
  return source !== "manheim" || capability.mode === "official_api";
}

export function getUnavailableAuctionSources(
  sources: readonly AuctionSource[] | null | undefined,
  capabilities: AuctionSourceCapabilities | null | undefined,
): AuctionSource[] {
  if (!capabilities) {
    return (sources ?? []).filter((source) => source === "manheim");
  }
  return (sources ?? []).filter(
    (source) => !isAuctionSourceCapabilityAvailable(source, capabilities.sources[source]),
  );
}

export function auctionSourceLabel(source: AuctionSource): string {
  return AUCTION_SOURCES.find((item) => item.id === source)?.label ?? source;
}
