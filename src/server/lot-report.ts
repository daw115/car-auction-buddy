// Port 1:1 z Pythona report_generator.py — generator HTML brokera + klienta.
// Zachowuje strukturę danych LOT, CSS i sekcje. Pobiera zdjęcia jako base64.

export type LotCost = [name: string, opt: string, pess: string, note: string];
export type LotScoring = [delta: string, criterion: string, reason: string];
export type LotFlag = [bar: "r" | "a" | "g" | "ok", title: string, lvl: "crit" | "high" | "med" | "low", lvlLabel: string, desc: string];
export type LotRawField = [key: string, val: string, cls: "" | "ok" | "warn" | "bad"];
export type LotChecklistItem = [cls: "c" | "h" | "m" | "l", label: string, task: string];
export type LotBidStrategy = [label: string, val: string, isWarn: boolean];
export type LotStrategyNote = [key: string, val: string];

export interface Lot {
  source: string;
  lot_id: string;
  url: string;
  vin: string;
  generated_at: string;
  year: number | string;
  make: string;
  model: string;
  engine: string;
  transmission: string;
  drive: string;
  color: string;
  body: string;
  odometer_mi: number | null;
  odometer_note: string;
  airbags_deployed: boolean;
  keys: boolean | null;
  damage_primary: string;
  damage_secondary: string;
  damage_score: number;
  title_type: string;
  seller_type: string;
  location: string;
  location_note: string;
  auction_date: string;
  auction_deadline_pl: string;
  current_bid_usd: number;
  buy_now_usd: number | null;
  acv_usd: number;
  rc_usd: number;
  last_ask_usd: number;
  score: number;
  status: string;
  budget_note?: string;
  costs: LotCost[];
  cost_total_opt: string;
  cost_total_pess: string;
  scoring: LotScoring[];
  flags: LotFlag[];
  raw_fields: LotRawField[];
  checklist: LotChecklistItem[];
  bid_strategy: LotBidStrategy[];
  strategy_notes: LotStrategyNote[];
  image_urls: string[];
}

// ---------- helpers ----------
const PLACEHOLDER_IMG =
  "data:image/svg+xml;base64," +
  Buffer.from(
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200">' +
      '<rect width="300" height="200" fill="#d0d7de"/>' +
      '<text x="150" y="108" text-anchor="middle" fill="#57606a" ' +
      'font-size="14" font-family="sans-serif">brak zdjęcia</text></svg>',
    "utf-8",
  ).toString("base64");

export async function fetchImagesAsBase64(urls: string[], max = 8): Promise<string[]> {
  const out: string[] = [];
  for (const url of urls.slice(0, max)) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 10_000);
      const r = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0" },
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      if (!r.ok) {
        out.push(PLACEHOLDER_IMG);
        continue;
      }
      const buf = Buffer.from(await r.arrayBuffer());
      const ct = r.headers.get("content-type") || "image/jpeg";
      out.push(`data:${ct};base64,${buf.toString("base64")}`);
    } catch {
      out.push(PLACEHOLDER_IMG);
    }
  }
  return out;
}

const h = (v: unknown): string => {
  if (v === null || v === undefined) return "";
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
};
const fmtNum = (n: number) => n.toLocaleString("en-US").replace(/,/g, " ");

const scoreColor = (delta: string) =>
  delta.startsWith("+") ? "pos" : delta.startsWith("-") || delta.startsWith("−") ? "neg" : "";

const flagBarColor = (c: string) =>
  ({ r: "var(--red)", a: "var(--accent)", g: "var(--border)", ok: "var(--ok)" } as Record<string, string>)[c] || "var(--border)";
const flagTitleColor = (c: string) =>
  ({ r: "var(--red)", a: "var(--amber)", g: "var(--text)", ok: "var(--ok)" } as Record<string, string>)[c] || "var(--text)";
const levelCss = (lvl: string) =>
  ({
    crit: "background:#fff0f0;color:#cf222e",
    high: "background:#fff4ee;color:#9a3412",
    med: "background:#fffbe6;color:#7a4f00",
    low: "background:#f6f8fa;color:#57606a",
  } as Record<string, string>)[lvl] || "";
const statusColors = (status: string): [string, string] => {
  const s = status.toUpperCase();
  if (s.includes("REKOMENDACJA")) return ["#eafbee", "#1a7f37"];
  if (s.includes("ODRZUĆ") || s.includes("ODRZUC")) return ["#fff0f0", "#cf222e"];
  return ["#fffbe6", "#7a4f00"];
};

// ---------- COMMON CSS ----------
export const COMMON_CSS = `
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --navy:#0a2540;--navy2:#0d2f50;--blue:#1a56a0;--accent:#f0a500;
  --ok:#1a7f37;--ok-bg:#eafbee;--ok-bdr:#b2dfbb;
  --warn:#9a3412;--warn-bg:#fff4ee;
  --amber:#7a4f00;--amber-bg:#fffbe6;--amber-bdr:#f4d27a;
  --red:#cf222e;--red-bg:#fff0f0;--red-bdr:#f5c6cb;
  --text:#1f2328;--muted:#57606a;--border:#d0d7de;
  --panel:#f6f8fa;--white:#fff;
}
body{font-family:"DM Sans",Arial,sans-serif;background:#e8edf4;color:var(--text);
  font-size:13.5px;line-height:1.55;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.page{max-width:900px;margin:24px auto;background:var(--white);border-radius:14px;overflow:hidden;
  box-shadow:0 2px 8px rgba(0,0,0,.1),0 16px 48px rgba(10,37,64,.12)}
.dtbl{width:100%;border-collapse:collapse;border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:13px}
.dtbl tr:nth-child(even) td{background:var(--panel)}
.dtbl td{padding:7px 11px;border-bottom:1px solid var(--border)}
.dtbl tr:last-child td{border-bottom:none}
.dk{color:var(--muted);font-weight:500;width:38%}
.dv{font-weight:600;border-left:1px solid var(--border)}
.dv.bad{color:var(--red)}.dv.ok{color:var(--ok)}.dv.warn{color:var(--amber)}
.dv.mono{font-family:"DM Mono",monospace;font-size:11.5px;font-weight:500}
.htbl{width:100%;border-collapse:collapse;border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:12.5px}
.htbl thead tr{background:var(--navy2);color:#fff}
.htbl thead th{padding:7px 10px;text-align:left;font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.htbl thead th.c{text-align:center;width:52px}
.htbl tbody tr:nth-child(even) td{background:var(--panel)}
.htbl tbody td{padding:6px 10px;border-bottom:1px solid var(--border)}
.htbl tbody tr:last-child td{border-bottom:none}
.htbl .pos{color:var(--ok);font-weight:700;text-align:center}
.htbl .neg{color:var(--red);font-weight:700;text-align:center}
.htbl tfoot td{padding:8px 10px;font-weight:700;background:var(--amber-bg)}
.htbl tfoot .c{text-align:center;color:var(--amber);font-size:15px}
.ctbl{width:100%;border-collapse:collapse;border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:12.5px}
.ctbl thead tr{background:var(--navy2);color:#fff}
.ctbl thead th{padding:7px 10px;text-align:left;font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
.ctbl thead th.r{text-align:right}
.ctbl tbody tr:nth-child(even) td{background:var(--panel)}
.ctbl tbody td{padding:6px 10px;border-bottom:1px solid var(--border)}
.ctbl .num{text-align:right;font-family:"DM Mono",monospace;font-weight:600}
.ctbl .note{color:var(--muted);font-size:11.5px}
.ctbl tfoot .opt td{background:#e6f4ea;font-weight:700;padding:8px 10px}
.ctbl tfoot .pess td{background:#fff1f0;font-weight:700;padding:8px 10px}
.ctbl tfoot .opt .num{color:var(--ok)}
.ctbl tfoot .pess .num{color:var(--red)}
.rtbl{width:100%;border-collapse:collapse;border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:12px}
.rtbl tr:nth-child(even) td{background:var(--panel)}
.rtbl td{padding:5px 10px;border-bottom:1px solid var(--border)}
.rtbl tr:last-child td{border-bottom:none}
.rk{color:var(--muted);font-weight:500;font-size:11px;width:30%}
.rv{font-family:"DM Mono",monospace;font-size:11px;font-weight:500;border-left:1px solid var(--border)}
.rv.bad{color:var(--red);font-family:"DM Sans",sans-serif;font-weight:700}
.rv.ok{color:var(--ok);font-family:"DM Sans",sans-serif;font-weight:700}
.rv.warn{color:var(--amber);font-family:"DM Sans",sans-serif;font-weight:600}
.chtbl{width:100%;border-collapse:collapse;border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:12.5px}
.chtbl thead tr{background:var(--navy2);color:#fff}
.chtbl thead th{padding:7px 10px;text-align:left;font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.chtbl tbody tr:nth-child(even) td{background:var(--panel)}
.chtbl tbody td{padding:7px 10px;border-bottom:1px solid var(--border);vertical-align:middle}
.chtbl tbody tr:last-child td{border-bottom:none}
.cnum{text-align:center;color:var(--muted);font-weight:600;width:24px}
.ccheck{text-align:center;color:var(--border);font-size:14px;width:24px}
.cprio{font-size:9.5px;font-weight:700;padding:2px 6px;border-radius:4px;letter-spacing:.04em;white-space:nowrap;display:inline-block}
.cprio.c{background:var(--red-bg);color:var(--red)}
.cprio.h{background:var(--warn-bg);color:var(--warn)}
.cprio.m{background:var(--amber-bg);color:var(--amber)}
.cprio.l{background:var(--panel);color:var(--muted)}
.btbl{width:100%;border-collapse:collapse;border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:13px}
.btbl tr:nth-child(even) td{background:var(--panel)}
.btbl td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:top}
.btbl tr:last-child td{border-bottom:none}
.bk{font-weight:700;width:170px;white-space:nowrap}
.bv{color:var(--muted)}.bv.wrn{color:var(--red);font-weight:600}
.notes-tbl{width:100%;border-collapse:collapse;font-size:13px}
.notes-tbl td{padding:8px 10px 8px 0;vertical-align:top;border-bottom:1px solid var(--border)}
.notes-tbl tr:last-child td{border-bottom:none}
.nk{font-weight:700;color:var(--navy);width:190px;white-space:nowrap;padding-right:16px}
.nv{color:var(--muted);line-height:1.6}
.stats{width:100%;border-collapse:collapse;border-bottom:1px solid var(--border)}
.stats td{padding:14px 10px;text-align:center;border-right:1px solid var(--border)}
.stats td:last-child{border-right:none}
.sv{font-size:20px;font-weight:700;color:var(--navy);line-height:1;margin-bottom:3px}
.sv.acc{color:var(--accent)}.sv.ok{color:var(--ok)}
.sv.red{color:var(--red)}.sv.amb{color:var(--amber)}
.sl{font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
.pill{display:inline-block;background:var(--navy2);color:#fff;font-size:9.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:5px 12px;border-radius:5px;margin-bottom:12px}
.pill.red{background:var(--red)}.pill.amber{background:#8a5c00}
.pill.ok{background:var(--ok)}.pill.blue{background:var(--blue)}
.section{margin-bottom:26px}
.divider{height:1px;background:var(--border);margin:18px 0}
.footer{text-align:center;font-size:11px;color:var(--muted);padding-bottom:4px}
@media print{body{background:#fff}.page{margin:0;box-shadow:none;border-radius:0}}
`;

export const CLIENT_CSS = `
.hero{background:var(--navy);padding:32px 36px 26px;border-bottom:3px solid var(--accent);position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;inset:0;background:
  radial-gradient(ellipse at 88% -25%,rgba(26,86,160,.55) 0%,transparent 55%),
  radial-gradient(ellipse at -5% 115%,rgba(240,165,0,.18) 0%,transparent 50%)}
.hero>*{position:relative}
.hpill{display:inline-block;padding:4px 11px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
.hpill.ok{background:rgba(26,127,55,.3);color:#6ee08a;border:1px solid rgba(110,224,138,.25)}
.hpill.blue{background:rgba(26,86,160,.35);color:#93c5fd;border:1px solid rgba(147,197,253,.25)}
.hpill.warn{background:rgba(207,34,46,.25);color:#fca5a5;border:1px solid rgba(252,165,165,.25)}
.headline{margin-bottom:20px;border-left:4px solid var(--accent);padding:13px 17px;background:var(--panel);border-radius:0 9px 9px 0}
.headline h2{font-size:19px;font-weight:700;color:var(--navy);line-height:1.25;margin-bottom:4px}
.headline h2 span{color:var(--blue)}
.headline p{font-size:13.5px;color:var(--muted);line-height:1.5}
.story p{font-size:13.5px;line-height:1.7;color:var(--text);margin-bottom:10px}
.story p:last-child{margin-bottom:0}
.spec{width:100%;border-collapse:collapse;margin-bottom:18px}
.spec td{padding:7px 10px;border-bottom:1px solid var(--border);vertical-align:top;font-size:13px}
.spec tr:last-child td{border-bottom:none}
.spec tr:nth-child(even) td{background:var(--panel)}
.sfeat{font-weight:600;color:var(--navy);width:36%;padding-right:10px}
.sarr{color:var(--accent);font-weight:700;width:16px}
.sben{color:var(--text)}
.dmg{display:table;width:100%;margin-bottom:6px;border:1px solid var(--border);border-radius:7px;overflow:hidden;font-size:13px}
.dmg-bar{display:table-cell;width:4px}
.dmg-cnt{display:table-cell;padding:8px 13px}
.dmg-title{font-weight:700;margin-bottom:2px;font-size:13px}
.cta{background:var(--navy);border-radius:10px;padding:20px 24px;border-top:3px solid var(--accent);margin-top:20px}
.cta h3{font-size:17px;font-weight:700;color:#fff;margin-bottom:6px}
.cta p{font-size:13px;color:#8ba8c8;line-height:1.6;margin-bottom:14px}
.cta-urgency{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:9px 12px;margin-bottom:14px}
.cta-urgency td{padding:3px 6px 3px 0;font-size:12.5px;color:#8ba8c8;vertical-align:top}
.cu-icon{color:var(--accent);font-weight:700;width:18px;white-space:nowrap}
.cu-val{color:#c8d8ea}
.cta-btn{display:inline-block;background:var(--accent);color:var(--navy);text-decoration:none;padding:10px 22px;border-radius:7px;font-size:13.5px;font-weight:700}
.docs{margin:12px 0;border-collapse:collapse;width:100%}
.docs td{padding:4px 10px 4px 0;font-size:13px;color:var(--text);vertical-align:top}
.dchk{color:var(--ok);font-weight:700;width:18px}
.tl{width:100%;border-collapse:collapse;margin:12px 0 16px}
.tl td{padding:7px 10px;border:1px solid var(--border);text-align:center;font-size:12px;background:var(--panel)}
.tday{font-weight:700;color:var(--blue);font-size:11px;display:block;margin-bottom:2px}
.fnote{font-size:11.5px;color:var(--muted);line-height:1.55;padding:14px 0 0;border-top:1px solid var(--border);margin-top:16px}
`;

// ---------- BROKER sections ----------
function brokerHero(lot: Lot): string {
  const [sbg, stc] = statusColors(lot.status);
  return `
<div style="background:var(--navy2);padding:26px 38px 22px;border-bottom:3px solid var(--red)">
  <div style="display:table;width:100%">
    <div style="display:table-cell;vertical-align:top">
      <div style="display:inline-block;background:var(--red);color:#fff;font-size:9.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;padding:4px 12px;border-radius:4px;margin-bottom:10px">
        Poufne &mdash; tylko do użytku wewnętrznego
      </div>
      <div style="font-size:25px;font-weight:700;color:#fff;line-height:1.15;margin-bottom:4px;letter-spacing:-.02em">
        ${h(lot.year)} ${h(lot.make)} ${h(lot.model)} &mdash; Raport Brokera
      </div>
      <div style="font-size:13px;color:#7a9ab8">
        Lot #${h(lot.lot_id)} &nbsp;&middot;&nbsp;
        ${h(lot.source.toUpperCase())} &nbsp;&middot;&nbsp;
        ${h(lot.location)} &nbsp;&middot;&nbsp;
        Pipeline aukcyjny v1.0
      </div>
    </div>
    <div style="display:table-cell;vertical-align:top;text-align:right;width:120px">
      <div style="font-size:40px;font-weight:700;color:var(--accent);line-height:1">${h(lot.score)}</div>
      <div style="font-size:9.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);opacity:.7">/ 10</div>
      <div style="display:inline-block;margin-top:6px;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;background:${sbg};color:${stc};border:1.5px solid ${stc}40">
        ${h(lot.status)}
      </div>
    </div>
  </div>
  <div style="font-size:11px;color:#5a7a98;border-top:1px solid rgba(255,255,255,.08);padding-top:12px;margin-top:14px">
    &#128197; Wygenerowano: ${h(lot.generated_at)} &nbsp;&nbsp;
    &#128269; Kryteria: ${h(lot.make)} ${h(lot.model)} &middot; ${h(lot.budget_note ?? "—")} &nbsp;&nbsp;
    &#128230; Źródła: ${h(lot.source.toUpperCase())} &nbsp;&nbsp;
    &#9940; Wykluczone: Flood, Fire
  </div>
</div>`;
}

function brokerStats(lot: Lot): string {
  const keysLabel = lot.keys === false ? "NIE" : lot.keys === true ? "TAK" : "brak danych";
  const keysCls = lot.keys ? "ok" : "red";
  const airCls = !lot.airbags_deployed ? "ok" : "red";
  const airLabel = !lot.airbags_deployed ? "Nie odpalone" : "ODPALONE";
  return `
<table class="stats" cellspacing="0" cellpadding="0"><tbody><tr>
  <td><div class="sv amb">${h(lot.score)}/10</div><div class="sl">Score</div></td>
  <td><div class="sv red">${h(lot.damage_score)}/100</div><div class="sl">Damage score</div></td>
  <td><div class="sv">${h(fmtNum(lot.acv_usd))} USD</div><div class="sl">ACV Copart</div></td>
  <td><div class="sv ok">${h(lot.cost_total_opt)} USD</div><div class="sl">Koszt opt.</div></td>
  <td><div class="sv red">${h(lot.cost_total_pess)} USD</div><div class="sl">Koszt pesym.</div></td>
  <td><div class="sv ${airCls}">${airLabel}</div><div class="sl">Airbagi</div></td>
  <td><div class="sv ${keysCls}">${keysLabel}</div><div class="sl">Klucze</div></td>
</tr></tbody></table>`;
}

function brokerLotData(lot: Lot): string {
  const odo = lot.odometer_mi ? `${fmtNum(lot.odometer_mi)} mi` : "NULL";
  const odoCls = lot.odometer_mi ? "" : "bad";
  const keysVal = lot.keys === true ? "TAK" : lot.keys === false ? "NIE &#9888;" : "brak danych";
  const keysCls = lot.keys ? "ok" : "bad";
  const airVal = !lot.airbags_deployed ? "FALSE &mdash; nie odpalone &#10003;" : "TRUE &mdash; ODPALONE &#9888;";
  const airCls = !lot.airbags_deployed ? "ok" : "bad";
  const tt = lot.title_type.toUpperCase();
  const titleCls = tt.includes("SALVAGE") ? "bad" : tt.includes("CLEAN") ? "ok" : "warn";
  const rows = `
    <tr><td class="dk">lot_id / source</td><td class="dv mono">${h(lot.lot_id)} / ${h(lot.source)}</td></tr>
    <tr><td class="dk">URL</td><td class="dv"><a href="${h(lot.url)}" style="color:var(--blue)">${h(lot.url.slice(0, 60))}...</a></td></tr>
    <tr><td class="dk">VIN</td><td class="dv mono">${h(lot.vin)}</td></tr>
    <tr><td class="dk">year / make / model</td><td class="dv">${h(lot.year)} / ${h(lot.make)} / ${h(lot.model)}</td></tr>
    <tr><td class="dk">engine</td><td class="dv">${h(lot.engine)}</td></tr>
    <tr><td class="dk">transmission / drive</td><td class="dv">${h(lot.transmission)} / ${h(lot.drive)}</td></tr>
    <tr><td class="dk">color / body</td><td class="dv">${h(lot.color)} / ${h(lot.body)}</td></tr>
    <tr><td class="dk">odometer_mi</td><td class="dv ${odoCls}">${odo}</td></tr>
    <tr><td class="dk">odometer_note (ord)</td><td class="dv bad">${h(lot.odometer_note)}</td></tr>
    <tr><td class="dk">damage_primary</td><td class="dv bad">${h(lot.damage_primary)}</td></tr>
    <tr><td class="dk">damage_secondary</td><td class="dv warn">${h(lot.damage_secondary)}</td></tr>
    <tr><td class="dk">damage_score</td><td class="dv bad">${h(lot.damage_score)} / 100</td></tr>
    <tr><td class="dk">title_type</td><td class="dv ${titleCls}">${h(lot.title_type)}</td></tr>
    <tr><td class="dk">seller_type</td><td class="dv ok">${h(lot.seller_type)}</td></tr>
    <tr><td class="dk">location</td><td class="dv">${h(lot.location)} (${h(lot.location_note)})</td></tr>
    <tr><td class="dk">auction_date</td><td class="dv">${h(lot.auction_date)}</td></tr>
    <tr><td class="dk">current_bid_usd</td><td class="dv">${h(lot.current_bid_usd)} USD</td></tr>
    <tr><td class="dk">buy_now_usd</td><td class="dv">${lot.buy_now_usd ? h(lot.buy_now_usd) : "NULL"}</td></tr>
    <tr><td class="dk">ACV (lotPlugAcv)</td><td class="dv warn">${h(fmtNum(lot.acv_usd))} USD</td></tr>
    <tr><td class="dk">RC (replacement cost)</td><td class="dv">${h(fmtNum(lot.rc_usd))} USD</td></tr>
    <tr><td class="dk">last_ask (la)</td><td class="dv warn">${h(fmtNum(lot.last_ask_usd))} USD</td></tr>
    <tr><td class="dk">airbags_deployed</td><td class="dv ${airCls}">${airVal}</td></tr>
    <tr><td class="dk">keys (hk)</td><td class="dv ${keysCls}">${keysVal}</td></tr>`;
  return `<table class="dtbl" cellspacing="0" cellpadding="0"><tbody>${rows}</tbody></table>`;
}

function brokerScoring(lot: Lot): string {
  const rows = lot.scoring
    .map(([delta, criterion, reason]) => `<tr><td>${h(criterion)}</td><td class="${scoreColor(delta)}">${h(delta)}</td><td>${h(reason)}</td></tr>`)
    .join("");
  return `
<table class="htbl" cellspacing="0" cellpadding="0">
<thead><tr><th>Kryterium</th><th class="c">&Delta;</th><th>Uzasadnienie operacyjne</th></tr></thead>
<tbody>${rows}</tbody>
<tfoot><tr><td><strong>SCORE KOŃCOWY</strong></td><td class="c"><strong>${h(lot.score)}</strong></td><td>Status: <strong>${h(lot.status)}</strong></td></tr></tfoot>
</table>`;
}

function brokerCosts(lot: Lot): string {
  const rows = lot.costs
    .map(([name, opt, pess, note]) => `<tr><td>${h(name)}</td><td class="num">${h(opt)}</td><td class="num">${h(pess)}</td><td class="note">${h(note)}</td></tr>`)
    .join("");
  return `
<table class="ctbl" cellspacing="0" cellpadding="0">
<thead><tr><th>Składnik</th><th class="r">Opt. (USD)</th><th class="r">Pesym. (USD)</th><th>Uwagi</th></tr></thead>
<tbody>${rows}</tbody>
<tfoot>
  <tr class="opt"><td><strong>ŁĄCZNIE opt.</strong></td><td class="num">${h(lot.cost_total_opt)} USD</td><td class="num">&mdash;</td><td class="note">Bez niespodzianek strukturalnych</td></tr>
  <tr class="pess"><td><strong>ŁĄCZNIE pesym.</strong></td><td class="num">&mdash;</td><td class="num">${h(lot.cost_total_pess)} USD</td><td class="note">Z ukrytymi uszkodzeniami</td></tr>
</tfoot></table>`;
}

function brokerFlags(lot: Lot): string {
  return lot.flags
    .map(([bar, title, lvl, lvlLabel, desc]) => `
<div style="display:table;width:100%;margin-bottom:7px;border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:13px">
  <div style="display:table-cell;width:4px;background:${flagBarColor(bar)}">&nbsp;</div>
  <div style="display:table-cell;padding:9px 13px">
    <table width="100%" cellspacing="0"><tbody><tr>
      <td style="font-weight:700;color:${flagTitleColor(bar)}">${h(title)}</td>
      <td style="text-align:right;white-space:nowrap">
        <span style="font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:4px;${levelCss(lvl)}">${h(lvlLabel)}</span>
      </td>
    </tr></tbody></table>
    <div style="color:var(--muted);font-size:12.5px;line-height:1.5;margin-top:3px">${h(desc)}</div>
  </div>
</div>`)
    .join("");
}

function brokerRawFields(lot: Lot): string {
  const rows = lot.raw_fields.map(([k, v, c]) => `<tr><td class="rk">${h(k)}</td><td class="rv ${c}">${h(v)}</td></tr>`).join("");
  return `<table class="rtbl" cellspacing="0" cellpadding="0"><tbody>${rows}</tbody></table>`;
}

function brokerPhotos(images: string[], lot: Lot): string {
  if (!images.length) return "";
  const main = images[0];
  const thumbs = images.slice(1);
  let thumbRows = "";
  for (let i = 0; i < thumbs.length; i += 3) {
    const chunk = thumbs.slice(i, i + 3);
    while (chunk.length < 3) chunk.push(PLACEHOLDER_IMG);
    const cells = chunk
      .map((c) => `<td style="padding:0 3px 0 0;width:33%"><img src="${c}" style="width:100%;height:auto;display:block;border-radius:6px;border:1px solid var(--border)"></td>`)
      .join("");
    thumbRows += `<tr>${cells}</tr><tr><td colspan='3' style='height:5px'></td></tr>`;
  }
  const alt = `${lot.year} ${lot.make} ${lot.model}`;
  return `
<img src="${main}" style="width:100%;height:auto;display:block;border-radius:8px;border:1px solid var(--border);margin-bottom:6px" alt="${h(alt)} — widok główny">
<table width="100%" cellspacing="0" cellpadding="0"><tbody>${thumbRows}</tbody></table>`;
}

function brokerChecklist(lot: Lot): string {
  const rows = lot.checklist
    .map(([cls, label, task], i) => `<tr><td class="cnum">${i + 1}</td><td>${h(task)}</td><td style="text-align:center"><span class="cprio ${cls}">${h(label)}</span></td><td class="ccheck">&#9744;</td></tr>`)
    .join("");
  return `
<table class="chtbl" cellspacing="0" cellpadding="0">
<thead><tr><th style="width:24px">#</th><th>Zadanie</th><th style="width:90px;text-align:center">Priorytet</th><th style="width:24px;text-align:center">&#10003;</th></tr></thead>
<tbody>${rows}</tbody></table>`;
}

function brokerBid(lot: Lot): string {
  const rows = lot.bid_strategy
    .map(([label, val, isWarn]) => `<tr><td class="bk">${h(label)}</td><td class="${isWarn ? "bv wrn" : "bv"}">${h(val)}</td></tr>`)
    .join("");
  return `<table class="btbl" cellspacing="0" cellpadding="0"><tbody>${rows}</tbody></table>`;
}

function brokerStrategy(lot: Lot): string {
  const rows = lot.strategy_notes.map(([k, v]) => `<tr><td class="nk">${h(k)}</td><td class="nv">${h(v)}</td></tr>`).join("");
  return `<table class="notes-tbl" cellspacing="0" cellpadding="0"><tbody>${rows}</tbody></table>`;
}

function brokerSection(lot: Lot, images: string[]): string {
  const photoCount = images.filter((x) => x && !x.includes("svg+xml")).length;
  return `
${brokerHero(lot)}
${brokerStats(lot)}
<div style="padding:24px 38px 34px">
  <div class="section"><span class="pill">&#9658; Dane lotu &mdash; identyfikacja</span>${brokerLotData(lot)}</div>
  <div class="section"><span class="pill">&#9658; Scoring breakdown &mdash; ${h(lot.score)} / 10</span>${brokerScoring(lot)}</div>
  <div class="section"><span class="pill">&#9658; Kalkulacja kosztów importu</span>${brokerCosts(lot)}</div>
  <div class="section"><span class="pill red">&#9658; Czerwone flagi &mdash; ocena brokera</span>${brokerFlags(lot)}</div>
  <div class="section"><span class="pill blue">&#9658; Kluczowe pola API &mdash; raw</span>${brokerRawFields(lot)}</div>
  <div class="section"><span class="pill">&#9658; Zdjęcia z aukcji (${photoCount} szt.)</span>${brokerPhotos(images, lot)}</div>
  <div class="section"><span class="pill">&#9658; Checklist przed licytacją</span>${brokerChecklist(lot)}</div>
  <div class="section"><span class="pill">&#9658; Strategia licytacji</span>${brokerBid(lot)}</div>
  <div class="section"><span class="pill amber">&#9658; Notatki strategiczne (copywriting)</span>${brokerStrategy(lot)}</div>
</div>`;
}

export function buildBrokerHtml(lots: Array<{ lot: Lot; images: string[]; group: "TOP" | "REJECTED" }>): string {
  const tops = lots.filter((x) => x.group === "TOP");
  const rejs = lots.filter((x) => x.group === "REJECTED");
  const block = (label: string, items: typeof lots, color: string) => {
    if (!items.length) return "";
    return `
<div style="background:${color};color:#fff;padding:14px 38px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:12px">
  ${label} (${items.length})
</div>
${items.map((x) => `<div class="page" style="margin-top:0;border-radius:0">${brokerSection(x.lot, x.images)}</div>`).join("")}`;
  };
  const first = lots[0]?.lot;
  const title = first ? `BROKER — ${first.make} ${first.model} +${lots.length - 1}` : "BROKER";
  return `<!DOCTYPE html>
<html lang="pl"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${h(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>${COMMON_CSS}</style></head>
<body>
${block("TOP rekomendacje brokera", tops, "var(--ok)")}
${block("Odrzucone — uzasadnienie", rejs, "var(--red)")}
<div style="text-align:center;font-size:11px;color:var(--muted);padding:18px">
  Dokument POUFNY — wyłącznie do użytku wewnętrznego brokera. Nie udostępniać klientowi.
</div>
</body></html>`;
}

// ---------- CLIENT html (per lot, marketing) ----------
export function buildClientHtml(lot: Lot, images: string[]): string {
  const mainImg = images[0] || PLACEHOLDER_IMG;
  const airOk = !lot.airbags_deployed;
  const airPill = airOk
    ? `<td><span class="hpill ok">Airbagi nie odpalone</span></td>`
    : `<td><span class="hpill warn">Airbagi ODPALONE</span></td>`;
  const titleCls = lot.title_type.toUpperCase().includes("SALVAGE") ? "warn" : "ok";
  const titlePill = `<td><span class="hpill ${titleCls}">${h(lot.title_type)}</span></td>`;

  const specRows = `
    <tr><td class="sfeat">${h(lot.engine)}</td><td class="sarr">&rarr;</td><td class="sben">Dynamika klasy premium. Przy spokojnej jeździe poniżej 10&thinsp;L/100&thinsp;km na trasie.</td></tr>
    <tr><td class="sfeat">${h(lot.drive)}</td><td class="sarr">&rarr;</td><td class="sben">Pewna trakcja zimą, reakcja w 100&thinsp;ms. Bezpieczny na śniegu.</td></tr>
    <tr><td class="sfeat">Skrzynia ${h(lot.transmission)}</td><td class="sarr">&rarr;</td><td class="sben">Zmiany biegów niezauważalne. Serwisowana w Polsce, sprawdzona konstrukcja.</td></tr>
    <tr><td class="sfeat">Sprzedawca: ${h(lot.seller_type)}</td><td class="sarr">&rarr;</td><td class="sben">Historia szkody w pełni udokumentowana. Brak ukrytego poprzedniego wypadku.</td></tr>
    <tr><td class="sfeat">Lokalizacja: ${h(lot.location)}</td><td class="sarr">&rarr;</td><td class="sben">${h(lot.location_note)} — krótsza i tańsza droga do portu.</td></tr>`;

  const engineFirstWord = lot.engine.split(" ")[0] || "V8";
  const auctionDateShort = lot.auction_date.split("·")[0]?.trim() ?? lot.auction_date;
  const airbagPara = !lot.airbags_deployed
    ? "Poduszki <strong>nie zadziałały</strong> &mdash; co potwierdza, że uderzenie nie przekroczyło progu aktywacji SRS. Silnik i skrzynia biegów są nieuszkodzone."
    : "";
  const sndDmgInline = lot.damage_secondary ? `i ${h(lot.damage_secondary.toLowerCase())}` : "";
  const sndDmgPlus = lot.damage_secondary ? ` + ${h(lot.damage_secondary)}` : "";
  const noDeploy = !lot.airbags_deployed ? "Airbagi nie odpalone &middot;" : "";

  return `<!DOCTYPE html>
<html lang="pl"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${h(lot.year)} ${h(lot.make)} ${h(lot.model)} &mdash; Oferta importu z USA</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>${COMMON_CSS}${CLIENT_CSS}</style></head>
<body>
<div class="page" style="max-width:740px">
<div class="hero">
  <div style="font-size:9.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:10px">
    Oferta przygotowana indywidualnie &nbsp;&middot;&nbsp; Import z USA
  </div>
  <div style="font-size:28px;font-weight:700;color:#fff;line-height:1.1;margin-bottom:5px;letter-spacing:-.025em">
    ${h(lot.make)} ${h(lot.model)} <span style="color:var(--accent)">${h(lot.year)}</span>
  </div>
  <div style="font-size:14px;color:#8ba8c8;margin-bottom:18px">
    ${h(lot.engine)} &middot; ${h(lot.drive)} &middot; ${h(lot.location)}
  </div>
  <table cellspacing="0" cellpadding="0"><tbody><tr>
    ${airPill}
    <td style="padding:0 8px 0 0"><span class="hpill blue">Sprzedawca: ${h(lot.seller_type)}</span></td>
    ${titlePill}
  </tr></tbody></table>
</div>
<div style="background:#111;line-height:0">
  <img src="${mainImg}" style="width:100%;height:240px;object-fit:cover;object-position:center;display:block" alt="${h(lot.year)} ${h(lot.make)} ${h(lot.model)}">
</div>
<div style="background:#111;color:#6e8ba8;font-size:10.5px;padding:5px 14px 7px;letter-spacing:.03em">
  Zdjęcie z aukcji ${h(lot.source.toUpperCase())} &nbsp;&middot;&nbsp; Lot #${h(lot.lot_id)} &nbsp;&middot;&nbsp; ${h(lot.location)}
</div>
<table class="stats" cellspacing="0" cellpadding="0"><tbody><tr>
  <td><div class="sv">${h(lot.year)}</div><div class="sl">Rocznik</div></td>
  <td><div class="sv acc">${h(engineFirstWord)} V8</div><div class="sl">Silnik</div></td>
  <td><div class="sv ok">AWD</div><div class="sl">Napęd 4&times;4</div></td>
  <td><div class="sv" style="color:var(--blue);font-size:14px">${h(auctionDateShort)}</div><div class="sl">Data aukcji</div></td>
</tr></tbody></table>
<div style="padding:24px 36px 30px">
  <div class="headline">
    <h2>Nie wygląda jak <span>show-off</span>. Jedzie lepiej niż większość.</h2>
    <p>${h(lot.make)} ${h(lot.model)} to wybór kogoś, kto zna różnicę &mdash; elegancki sedan ze specyfikacją, której w Polsce prawie nie ma.</p>
  </div>
  <div class="story" style="margin-bottom:18px">
    <p>Ten <strong>${h(lot.year)} ${h(lot.make)} ${h(lot.model)}</strong> pochodzi z ${h(lot.location)} &mdash; stanu bez soli drogowej przez większość roku. Na aukcję ubezpieczeniową trafił po kolizji, która uszkodziła ${h(lot.damage_primary.toLowerCase())} ${sndDmgInline} auta.</p>
    <p>Dlaczego tak się stało? W USA naprawa auta tej klasy kosztuje w autoryzowanym serwisie 10&ndash;14&thinsp;000&thinsp;USD. <strong>Ubezpieczyciel woli sprzedać auto na aukcji niż naprawiać &mdash; to arytmetyka, nie problem z pojazdem.</strong></p>
    <p>${airbagPara} Po naprawie i homologacji &mdash; pełnoprawne, zarejestrowane auto z kompletną historią.</p>
  </div>
  <table class="spec" cellspacing="0" cellpadding="0"><tbody>${specRows}</tbody></table>
  <div class="dmg"><table width="100%" cellspacing="0"><tbody><tr>
    <td class="dmg-bar" style="background:#e6a800">&nbsp;</td>
    <td class="dmg-cnt">
      <div class="dmg-title" style="color:var(--amber)">Co jest uszkodzone &mdash; mówimy o tym wprost</div>
      <div style="color:var(--muted);font-size:12.5px;line-height:1.45">
        ${h(lot.damage_primary)}${sndDmgPlus} &mdash; dokładny zakres potwierdzi nasz rzeczoznawca przed licytacją. <strong>Nie licytujemy bez tej weryfikacji.</strong>
      </div>
    </td>
  </tr></tbody></table></div>
  <div class="dmg" style="margin-bottom:18px"><table width="100%" cellspacing="0"><tbody><tr>
    <td class="dmg-bar" style="background:var(--ok)">&nbsp;</td>
    <td class="dmg-cnt">
      <div class="dmg-title" style="color:var(--ok)">Czego NIE było &mdash; potwierdzone</div>
      <div style="color:var(--muted);font-size:12.5px;line-height:1.45">
        ${noDeploy} Brak uszkodzeń od wody &middot; Brak historii kradzieży &middot; Sprzedawca ubezpieczeniowy = pełna historia szkody
      </div>
    </td>
  </tr></tbody></table></div>
  <table class="tl" cellspacing="0" cellpadding="0"><tbody><tr>
    <td><span class="tday">Dzień 0</span>Zakup na aukcji</td>
    <td><span class="tday">+7 dni</span>Załadunek na statek</td>
    <td><span class="tday">+32 dni</span>Port Gdynia / Bremerhaven</td>
    <td><span class="tday">+42 dni</span>Odprawa celna</td>
    <td><span class="tday">+75&ndash;85 dni</span><strong>Odbiór z tablicami</strong></td>
  </tr></tbody></table>
  <table class="docs" cellspacing="0" cellpadding="0"><tbody>
    <tr><td class="dchk">&#10003;</td><td>Raport CarFax / NMVTIS &mdash; pełna historia VIN</td></tr>
    <tr><td class="dchk">&#10003;</td><td>Dokumentacja naprawy &mdash; 50+ zdjęć na każdym etapie</td></tr>
    <tr><td class="dchk">&#10003;</td><td>Diagnoza komputerowa po naprawie &mdash; zero aktywnych błędów</td></tr>
    <tr><td class="dchk">&#10003;</td><td>Faktura VAT + tłumaczenie przysięgłe tytułu własności</td></tr>
    <tr><td class="dchk">&#10003;</td><td>Komplet do rejestracji &mdash; wyjeżdża Pan z tablicami</td></tr>
  </tbody></table>
  <div class="cta">
    <h3>15 minut, żeby zobaczyć pełny obraz.</h3>
    <p>Proponuję krótką rozmowę wideo &mdash; pokażę raport VIN, zdjęcia HD z aukcji i odpowiem na każde pytanie dotyczące techniki i procesu. Bez zobowiązań.</p>
    <table class="cta-urgency" cellspacing="0" cellpadding="0"><tbody>
      <tr><td class="cu-icon">&#9200;</td><td class="cu-val">Aukcja kończy się <strong>${h(lot.auction_deadline_pl)}</strong></td></tr>
      <tr><td class="cu-icon">&#128269;</td><td class="cu-val">${h(lot.make)} ${h(lot.model)} ${h(lot.year)} z taką specyfikacją pojawia się na Copart raz na 2&ndash;3 miesiące.</td></tr>
    </tbody></table>
    <a href="#" class="cta-btn">Umów 15-minutową rozmowę &rarr;</a>
  </div>
  <div class="fnote">
    Oferta dotyczy konkretnego pojazdu z aukcji ${h(lot.source.toUpperCase())} (Lot #${h(lot.lot_id)}). Cena finalna zależy od wyniku licytacji i kursu USD/PLN w dniu zakupu. Wszystkie dane techniczne potwierdzane przed licytacją w raporcie CarFax/NMVTIS i fizycznej weryfikacji zdjęć HD.
  </div>
</div>
</div>
</body></html>`;
}
