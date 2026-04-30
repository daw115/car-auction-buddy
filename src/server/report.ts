// HTML report renderer — mirrors usa-car-finder/report/templates/report.html.j2
// Output: standalone HTML document suitable for download or rendering as email.
// No DOCX, no PDF.
import type { AnalyzedLot } from "@/lib/types";

const esc = (v: unknown): string => {
  if (v === null || v === undefined) return "";
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
};
const dash = (v: unknown): string => (v === null || v === undefined || v === "" ? "—" : esc(v));
const fmtNum = (v: unknown): string => (typeof v === "number" ? v.toLocaleString("pl-PL") : dash(v));

export function renderReportHtml(opts: {
  clientName: string;
  generatedAt: string;
  lots: AnalyzedLot[];
}): string {
  const { lots } = opts;
  const total = lots.length;
  const polecam = lots.filter((l) => l.analysis.recommendation === "POLECAM").length;
  const ryzyko = lots.filter((l) => l.analysis.recommendation === "RYZYKO").length;
  const odrzuc = lots.filter((l) => l.analysis.recommendation === "ODRZUĆ").length;

  const lotHtml = lots
    .map((item) => {
      const { lot, analysis } = item;
      const recClass =
        analysis.recommendation === "POLECAM"
          ? "POLECAM"
          : analysis.recommendation === "RYZYKO"
          ? "RYZYKO"
          : "ODRZUC";
      const flags =
        analysis.red_flags && analysis.red_flags.length > 0
          ? `<div class="flags">${analysis.red_flags
              .map((f) => `<span class="flag">⚠ ${esc(f)}</span>`)
              .join("")}</div>`
          : "";
      const img =
        lot.images && lot.images[0]
          ? `<img src="${esc(lot.images[0])}" class="lot-image" alt="Zdjęcie pojazdu">`
          : "";
      const reserve = lot.seller_reserve_usd ? `$${fmtNum(lot.seller_reserve_usd)}` : "nieznana";
      const keys = lot.keys === true ? "Tak" : lot.keys === false ? "Nie" : "—";
      const airbags = lot.airbags_deployed ? "ODPALONE" : "OK";
      const loc = `${esc(lot.location_city ?? "")}${lot.location_state ? ", " : ""}${esc(
        lot.location_state ?? ""
      )}`;

      return `
<div class="lot">
  <div class="lot-header">
    <div>
      <strong style="font-size:13pt">${dash(lot.year)} ${esc(lot.make ?? "")} ${esc(lot.model ?? "")}</strong>
      <span style="color:#666; font-size:9pt; margin-left:8px">
        ${esc((lot.source ?? "").toUpperCase())} | Lot: ${esc(lot.lot_id)}
      </span>
    </div>
    <div style="display:flex; align-items:center; gap:14px">
      <span class="score">${analysis.score.toFixed(1)}/10</span>
      <span class="badge ${recClass}">${esc(analysis.recommendation)}</span>
    </div>
  </div>
  ${img}
  <div class="info-grid">
    <div class="info-item"><strong>Przebieg</strong>${dash(lot.odometer_mi)} mi / ${dash(lot.odometer_km)} km</div>
    <div class="info-item"><strong>Uszkodzenie główne</strong>${dash(lot.damage_primary)}</div>
    <div class="info-item"><strong>Tytuł</strong>${dash(lot.title_type)}</div>
    <div class="info-item"><strong>Aktualna oferta</strong>$${fmtNum(lot.current_bid_usd)}</div>
    <div class="info-item"><strong>Cena rezerwowa</strong>${reserve}</div>
    <div class="info-item"><strong>Sprzedawca</strong>${dash(lot.seller_type)}</div>
    <div class="info-item"><strong>Lokalizacja</strong>${loc || "—"}</div>
    <div class="info-item"><strong>Klucze</strong>${keys}</div>
    <div class="info-item"><strong>Poduszki</strong>${airbags}</div>
  </div>
  ${flags}
  <div class="description">${esc(analysis.client_description_pl)}</div>
  <div class="costs">
    Szacowany koszt naprawy: <span>$${fmtNum(analysis.estimated_repair_usd)}</span>
    &nbsp;|&nbsp;
    Łączny koszt (bid + naprawa + transport): <span>$${fmtNum(analysis.estimated_total_cost_usd)}</span>
  </div>
  ${analysis.ai_notes ? `<p style="font-size:9pt; color:#555; margin-top:8px"><em>Uwagi: ${esc(analysis.ai_notes)}</em></p>` : ""}
  ${lot.url ? `<p style="font-size:8pt; color:#888; margin-top:6px"><a href="${esc(lot.url)}">${esc(lot.url)}</a>${lot.enriched_by_extension ? " | ✓ Wzbogacono przez rozszerzenie" : ""}</p>` : ""}
</div>`;
    })
    .join("\n");

  return `<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8"><title>Raport — ${esc(opts.clientName)}</title>
<style>
  body { font-family: Arial, sans-serif; font-size: 11pt; color: #222; margin: 20mm; }
  h1 { font-size: 18pt; color: #1a3a5c; border-bottom: 2px solid #1a3a5c; padding-bottom: 6px; }
  h2 { font-size: 13pt; color: #1a3a5c; margin-top: 24px; }
  .lot { border: 1px solid #ccc; border-radius: 6px; margin-bottom: 24px; padding: 14px 18px; }
  .lot-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
  .badge { padding: 4px 12px; border-radius: 4px; font-weight: bold; font-size: 10pt; }
  .POLECAM { background: #d4edda; color: #155724; }
  .RYZYKO  { background: #fff3cd; color: #856404; }
  .ODRZUC  { background: #f8d7da; color: #721c24; }
  .score   { font-size: 20pt; font-weight: bold; color: #1a3a5c; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin: 10px 0; }
  .info-item { font-size: 9pt; }
  .info-item strong { display: block; color: #555; font-size: 8pt; text-transform: uppercase; }
  .description { font-style: italic; color: #333; margin: 10px 0; padding: 8px 12px; background: #f7f9fc; border-left: 3px solid #1a3a5c; }
  .flags { margin: 8px 0; }
  .flag { display: inline-block; background: #ffeeba; color: #856404; border-radius: 3px; padding: 2px 8px; font-size: 8pt; margin: 2px; }
  .costs { background: #f0f4f8; padding: 8px 12px; border-radius: 4px; font-size: 10pt; }
  .costs span { font-weight: bold; color: #1a3a5c; }
  .lot-image { width: 180px; height: 120px; object-fit: cover; border-radius: 4px; margin-right: 14px; }
  .summary { background: #1a3a5c; color: white; padding: 12px 18px; border-radius: 6px; margin-bottom: 24px; }
  .summary-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
  .summary-item { text-align: center; }
  .summary-item .num { font-size: 24pt; font-weight: bold; }
  .summary-item .lbl { font-size: 9pt; opacity: 0.8; }
</style></head><body>
<h1>Raport wyszukiwania aut z USA</h1>
<p>Klient: <strong>${esc(opts.clientName)}</strong> | Wygenerowano: ${esc(opts.generatedAt)} | Łączna liczba przeanalizowanych lotów: ${total}</p>
<div class="summary"><div class="summary-grid">
  <div class="summary-item"><div class="num" style="color:#7dffb3">${polecam}</div><div class="lbl">POLECAM</div></div>
  <div class="summary-item"><div class="num" style="color:#ffe08a">${ryzyko}</div><div class="lbl">RYZYKO</div></div>
  <div class="summary-item"><div class="num" style="color:#ff8a8a">${odrzuc}</div><div class="lbl">ODRZUĆ</div></div>
</div></div>
${lotHtml}
</body></html>`;
}

export function renderMailHtml(opts: {
  clientName: string;
  topLots: AnalyzedLot[];
  generatedAt: string;
}): string {
  const rows = opts.topLots
    .slice(0, 5)
    .map((item) => {
      const { lot, analysis } = item;
      return `<tr>
        <td style="padding:8px;border-bottom:1px solid #eee"><strong>${esc(lot.year ?? "")} ${esc(lot.make ?? "")} ${esc(lot.model ?? "")}</strong><br><span style="color:#666;font-size:11px">${esc((lot.source ?? "").toUpperCase())} · Lot ${esc(lot.lot_id)}</span></td>
        <td style="padding:8px;border-bottom:1px solid #eee">${esc(lot.location_state ?? "—")}</td>
        <td style="padding:8px;border-bottom:1px solid #eee">$${typeof lot.current_bid_usd === "number" ? lot.current_bid_usd.toLocaleString("pl-PL") : "—"}</td>
        <td style="padding:8px;border-bottom:1px solid #eee"><strong>${analysis.score.toFixed(1)}</strong> · ${esc(analysis.recommendation)}</td>
      </tr>`;
    })
    .join("");
  return `<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;color:#222;background:#f4f5f2;margin:0;padding:24px">
<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:8px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,0.06)">
<h2 style="color:#1a3a5c;margin-top:0">Cześć ${esc(opts.clientName)},</h2>
<p>Poniżej przesyłam wybrane oferty z aukcji Copart i IAAI dopasowane do Twoich kryteriów. Wygenerowano: ${esc(opts.generatedAt)}.</p>
<table style="width:100%;border-collapse:collapse;margin:16px 0">
<thead><tr style="background:#1a3a5c;color:#fff"><th align="left" style="padding:8px">Pojazd</th><th align="left" style="padding:8px">Stan</th><th align="left" style="padding:8px">Bid</th><th align="left" style="padding:8px">Ocena</th></tr></thead>
<tbody>${rows}</tbody></table>
<p style="font-size:12px;color:#666">Pełny raport HTML w załączniku. W razie pytań — daj znać.</p>
</div></body></html>`;
}
