// PDF report generator (react-pdf, działa w Workerach — pure JS, brak Chromium).
// Renderuje raport brokera lub klienta z AnalyzedLot[].

import React from "react";
import { Document, Page, Text, View, StyleSheet, renderToBuffer } from "@react-pdf/renderer";
import type { AnalyzedLot } from "@/lib/types";
import { calculateCost } from "@/lib/cost-calculator";

const styles = StyleSheet.create({
  page: { padding: 32, fontSize: 10, fontFamily: "Helvetica", color: "#1a1a1a" },
  header: { marginBottom: 16, borderBottomWidth: 2, borderBottomColor: "#0a0e14", paddingBottom: 8 },
  brand: { fontSize: 20, fontWeight: 700, color: "#0a0e14" },
  subtitle: { fontSize: 10, color: "#666", marginTop: 2 },
  lotCard: { marginBottom: 16, borderWidth: 1, borderColor: "#d0d7de", borderRadius: 4, padding: 10 },
  lotHeader: { flexDirection: "row", justifyContent: "space-between", marginBottom: 6 },
  lotTitle: { fontSize: 13, fontWeight: 700, color: "#0a0e14" },
  badge: { fontSize: 9, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3, fontWeight: 700 },
  badgePolecam: { backgroundColor: "#d4edda", color: "#155724" },
  badgeRyzyko: { backgroundColor: "#fff3cd", color: "#856404" },
  badgeOdrzuc: { backgroundColor: "#f8d7da", color: "#721c24" },
  scoreBox: { fontSize: 16, fontWeight: 700, color: "#0a0e14" },
  grid: { flexDirection: "row", flexWrap: "wrap", marginTop: 6 },
  field: { width: "50%", paddingVertical: 2, flexDirection: "row" },
  fieldLabel: { width: "45%", color: "#666", fontSize: 9 },
  fieldValue: { width: "55%", fontSize: 9, fontWeight: 700 },
  section: { marginTop: 8 },
  sectionTitle: { fontSize: 11, fontWeight: 700, color: "#0a0e14", marginBottom: 4 },
  description: { fontSize: 10, color: "#333", lineHeight: 1.4, marginTop: 4 },
  redFlag: { fontSize: 9, color: "#721c24", marginVertical: 1 },
  costBox: { marginTop: 6, padding: 6, backgroundColor: "#f6f8fa", borderRadius: 3 },
  costRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 1 },
  costLabel: { fontSize: 9, color: "#444" },
  costValue: { fontSize: 9, fontWeight: 700 },
  costTotal: { fontSize: 11, fontWeight: 700, color: "#0a0e14", marginTop: 4, borderTopWidth: 1, borderTopColor: "#d0d7de", paddingTop: 4 },
  footer: { position: "absolute", bottom: 16, left: 32, right: 32, fontSize: 8, color: "#999", textAlign: "center" },
});

function badgeStyle(rec: string) {
  if (rec === "POLECAM") return styles.badgePolecam;
  if (rec === "RYZYKO") return styles.badgeRyzyko;
  return styles.badgeOdrzuc;
}

interface ReportProps {
  clientName: string;
  generatedAt: string;
  lots: AnalyzedLot[];
  mode: "broker" | "client";
  fx: { usd_pln: number; usd_eur: number };
}

const ReportDoc: React.FC<ReportProps> = ({ clientName, generatedAt, lots, mode, fx }) => {
  return React.createElement(
    Document,
    {},
    React.createElement(
      Page,
      { size: "A4", style: styles.page },
      React.createElement(
        View,
        { style: styles.header },
        React.createElement(Text, { style: styles.brand }, "USA Car Scout"),
        React.createElement(
          Text,
          { style: styles.subtitle },
          `${mode === "broker" ? "Raport brokera" : "Oferta dla klienta"} · ${clientName} · ${generatedAt} · ${lots.length} ${lots.length === 1 ? "lot" : "lotów"}`,
        ),
      ),
      ...lots.map((al, idx) => {
        const lot = al.lot;
        const a = al.analysis;
        const cost = calculateCost(
          {
            car_price_usd: lot.current_bid_usd ?? 0,
            estimated_repair_usd: a.estimated_repair_usd ?? 0,
            state: lot.location_state,
            engine_cc: null,
            fuel: "gasoline",
          },
          fx,
        );
        return React.createElement(
          View,
          { key: idx, style: styles.lotCard, wrap: false },
          React.createElement(
            View,
            { style: styles.lotHeader },
            React.createElement(
              Text,
              { style: styles.lotTitle },
              `${idx + 1}. ${lot.year ?? ""} ${lot.make ?? ""} ${lot.model ?? ""} ${lot.trim ?? ""}`.trim(),
            ),
            React.createElement(
              View,
              { style: { flexDirection: "row", alignItems: "center" } },
              mode === "broker" &&
                React.createElement(Text, { style: [styles.badge, badgeStyle(a.recommendation)] }, a.recommendation),
              React.createElement(Text, { style: [styles.scoreBox, { marginLeft: 8 }] }, `${a.score.toFixed(1)}/10`),
            ),
          ),
          React.createElement(
            View,
            { style: styles.grid },
            field("Źródło", `${lot.source} #${lot.lot_id}`),
            field("VIN", lot.vin ?? "—"),
            field("Przebieg", lot.odometer_mi ? `${lot.odometer_mi.toLocaleString()} mi` : "—"),
            field("Lokalizacja", `${lot.location_city ?? ""} ${lot.location_state ?? ""}`.trim() || "—"),
            field("Uszkodzenie", `${lot.damage_primary ?? "—"}${lot.damage_secondary ? ` / ${lot.damage_secondary}` : ""}`),
            field("Tytuł", lot.title_type ?? "—"),
            field("Aktualna oferta", lot.current_bid_usd ? `$${lot.current_bid_usd.toLocaleString()}` : "—"),
            field("Aukcja", lot.auction_date ?? "—"),
          ),
          React.createElement(
            View,
            { style: styles.section },
            React.createElement(Text, { style: styles.sectionTitle }, mode === "broker" ? "Analiza brokera" : "Opis"),
            React.createElement(
              Text,
              { style: styles.description },
              mode === "broker" && a.ai_notes ? a.ai_notes : a.client_description_pl,
            ),
          ),
          mode === "broker" && a.red_flags.length > 0
            ? React.createElement(
                View,
                { style: styles.section },
                React.createElement(Text, { style: styles.sectionTitle }, "Czerwone flagi"),
                ...a.red_flags.map((f, i) =>
                  React.createElement(Text, { key: i, style: styles.redFlag }, `• ${f}`),
                ),
              )
            : null,
          React.createElement(
            View,
            { style: styles.costBox },
            React.createElement(Text, { style: styles.sectionTitle }, "Kalkulacja całkowitego kosztu"),
            costRow("Cena auta", `$${cost.car_price_usd.toLocaleString()}`),
            mode === "broker" ? costRow("Naprawa (szac.)", `$${cost.repair_usd.toLocaleString()}`) : null,
            costRow(`Transport (${cost.region})`, `$${cost.transport_usa_to_pl_usd.toLocaleString()}`),
            costRow("Cło + akcyza + VAT", `$${(cost.customs_duty_usd + cost.excise_tax_usd + cost.vat_usd).toLocaleString()}`),
            costRow("Opłaty + homologacja + marża", `$${(cost.port_fees_usd + cost.homologation_usd + cost.broker_margin_usd).toLocaleString()}`),
            React.createElement(
              View,
              { style: styles.costTotal },
              React.createElement(
                View,
                { style: styles.costRow },
                React.createElement(Text, { style: { fontSize: 11, fontWeight: 700 } }, "Razem (PLN)"),
                React.createElement(
                  Text,
                  { style: { fontSize: 11, fontWeight: 700, color: "#0a0e14" } },
                  `${cost.total_pln.toLocaleString()} zł`,
                ),
              ),
            ),
          ),
        );
      }),
      React.createElement(
        Text,
        { style: styles.footer, fixed: true },
        `USA Car Scout · ${generatedAt} · Raport wygenerowany automatycznie`,
      ),
    ),
  );
};

function field(label: string, value: string) {
  return React.createElement(
    View,
    { style: styles.field },
    React.createElement(Text, { style: styles.fieldLabel }, label),
    React.createElement(Text, { style: styles.fieldValue }, value),
  );
}

function costRow(label: string, value: string) {
  return React.createElement(
    View,
    { style: styles.costRow },
    React.createElement(Text, { style: styles.costLabel }, label),
    React.createElement(Text, { style: styles.costValue }, value),
  );
}

export async function generateReportPdf(props: ReportProps): Promise<Buffer> {
  const doc = React.createElement(ReportDoc, props);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return renderToBuffer(doc as any);
}
