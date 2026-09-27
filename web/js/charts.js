// Plotly chart builders.
import { COLORS, MODULE_PALETTE, inr, pct, spct } from "./ui.js";

const FONT = { family: "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size: 12, color: "#334155" };
const CONFIG = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"] };
const GRID = "#eef1f7";

function base(extra = {}) {
  return {
    font: FONT,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    margin: { l: 56, r: 20, t: 16, b: 48 },
    hoverlabel: { bgcolor: "#0f172a", bordercolor: "#0f172a", font: { color: "#fff", family: FONT.family, size: 12 } },
    legend: { orientation: "h", y: -0.16, x: 0, font: { size: 11.5 } },
    ...extra,
  };
}

function render(el, data, layout, onClick) {
  if (!window.Plotly) return;
  window.Plotly.react(el, data, layout, CONFIG);
  if (onClick) {
    el.removeAllListeners?.("plotly_click");
    el.on("plotly_click", (ev) => {
      const id = ev?.points?.[0]?.customdata;
      if (id) onClick(Array.isArray(id) ? id[0] : id);
    });
  }
}

function colorFor(key, value, i) {
  if (key === "module") return MODULE_PALETTE[i % MODULE_PALETTE.length];
  const map = { action: COLORS.action, quadrant: COLORS.quadrant, bcg: COLORS.bcg, plc_stage: COLORS.plc }[key] || {};
  return map[value] || MODULE_PALETTE[i % MODULE_PALETTE.length];
}

function groupBy(arr, key) {
  const m = new Map();
  arr.forEach((d) => { const k = d[key]; if (!m.has(k)) m.set(k, []); m.get(k).push(d); });
  return m;
}

const ORDER = {
  action: ["Invest", "Retain", "Refactor", "Monitor", "Sunset"],
  quadrant: ["Complexity Trap", "Strategic Heavyweight", "Efficient Core", "Low-Cost Long Tail"],
  bcg: ["Star", "Cash Cow", "Question Mark", "Dog"],
  plc_stage: ["Introduction", "Growth", "Maturity", "Decline"],
};

function sizeScale(values, min = 10, max = 46) {
  const vmax = Math.max(...values.map((v) => Math.sqrt(Math.max(v, 0))), 1);
  return (v) => min + (Math.sqrt(Math.max(v, 0)) / vmax) * (max - min);
}

const hoverFeature =
  "<b>%{text}</b><br>%{customdata[1]} · %{customdata[2]}<br>" +
  "Complexity %{customdata[3]:.0f} · ROI %{customdata[4]:.0f}<br>" +
  "Eng cost %{customdata[5]}/mo · Revenue %{customdata[6]}/mo<br>" +
  "Adoption %{customdata[7]} · Usage %{customdata[8]}<extra></extra>";

const featCustom = (d) => [d.feature_id, d.action, d.bcg, d.complexity_index, d.roi_index, inr(d.eng_cost_monthly),
  inr(d.monthly_revenue_inr), pct(d.adoption_rate, 1), spct(d.usage_growth)];

// ---------------------------------------------------------------------------
export function complexityMatrix(el, features, params, { colorBy = "action", sizeBy = "eng_cost_monthly", labels = true, height = 560 } = {}, onClick) {
  const ct = params.complexity_threshold, rt = params.roi_threshold;
  const size = sizeScale(features.map((d) => d[sizeBy]));
  const groups = groupBy(features, colorBy);
  const keys = [...groups.keys()].sort((a, b) => (ORDER[colorBy]?.indexOf(a) ?? 0) - (ORDER[colorBy]?.indexOf(b) ?? 0) || String(a).localeCompare(String(b)));
  const data = keys.map((k, i) => {
    const pts = groups.get(k);
    return {
      type: "scatter", mode: labels ? "markers+text" : "markers", name: k,
      x: pts.map((d) => d.complexity_index), y: pts.map((d) => d.roi_index),
      text: pts.map((d) => d.feature_name),
      textposition: "top center", textfont: { size: 10, color: "#475569" },
      customdata: pts.map(featCustom),
      hovertemplate: hoverFeature,
      marker: { size: pts.map((d) => size(d[sizeBy])), color: colorFor(colorBy, k, i), opacity: 0.82, line: { color: "#fff", width: 1.5 } },
    };
  });
  const q = (x0, x1, y0, y1, color) => ({ type: "rect", layer: "below", xref: "x", yref: "y", x0, x1, y0, y1, fillcolor: color, line: { width: 0 } });
  const lab = (x, y, text, color, xanchor, yanchor) => ({ x, y, xref: "x", yref: "y", text, showarrow: false, xanchor, yanchor, font: { size: 12, color, family: FONT.family }, bgcolor: "rgba(255,255,255,.7)" });
  const layout = base({
    height,
    xaxis: { title: { text: "Complexity Index → (maintenance hours, bugs, friction)" }, range: [-4, 104], gridcolor: GRID, zeroline: false },
    yaxis: { title: { text: "ROI Index → (adoption × revenue, enterprise reliance)" }, range: [-4, 104], gridcolor: GRID, zeroline: false },
    shapes: [
      q(ct, 104, -4, rt, "rgba(220,38,38,.07)"), q(ct, 104, rt, 104, "rgba(217,119,6,.06)"),
      q(-4, ct, rt, 104, "rgba(5,150,105,.06)"), q(-4, ct, -4, rt, "rgba(148,163,184,.08)"),
      { type: "line", x0: ct, x1: ct, y0: -4, y1: 104, line: { color: "#94a3b8", dash: "dot", width: 1.5 } },
      { type: "line", x0: -4, x1: 104, y0: rt, y1: rt, line: { color: "#94a3b8", dash: "dot", width: 1.5 } },
    ],
    annotations: [
      lab(102, -2, "<b>COMPLEXITY TRAPS</b><br>high cost · low return", "#b91c1c", "right", "bottom"),
      lab(102, 102, "<b>STRATEGIC HEAVYWEIGHTS</b><br>high cost · high return", "#b45309", "right", "top"),
      lab(-2, 102, "<b>EFFICIENT CORE</b><br>low cost · high return", "#047857", "left", "top"),
      lab(-2, -2, "<b>LOW-COST LONG TAIL</b><br>low cost · low return", "#475569", "left", "bottom"),
    ],
  });
  render(el, data, layout, onClick);
}

// ---------------------------------------------------------------------------
export function bcgMatrix(el, features, params, onClick, height = 560) {
  const cap = 0.6;
  const labelSet = new Set([...features].sort((a, b) => b.monthly_revenue_inr - a.monthly_revenue_inr).slice(0, 6).map((d) => d.feature_id));
  features.filter((d) => d.complexity_index >= 75 && d.usage_growth <= cap).forEach((d) => labelSet.add(d.feature_id));
  const size = sizeScale(features.map((d) => d.monthly_revenue_inr), 12, 54);
  const xs = features.map((d) => Math.max(d.relative_share, 0.02));
  const data = [{
    type: "scatter", mode: "markers+text",
    x: xs, y: features.map((d) => Math.min(d.usage_growth, cap) * 100),
    text: features.map((d) => (labelSet.has(d.feature_id) ? d.feature_name : "")), textposition: "top center", textfont: { size: 10, color: "#475569" },
    hovertext: features.map((d) => d.feature_name),
    customdata: features.map(featCustom),
    hovertemplate: hoverFeature.replace("%{text}", "%{hovertext}"),
    marker: {
      size: features.map((d) => size(d.monthly_revenue_inr)),
      color: features.map((d) => d.complexity_index), cmin: 0, cmax: 100,
      colorscale: [[0, "#10b981"], [0.5, "#facc15"], [1, "#dc2626"]],
      colorbar: { title: { text: "Complexity", side: "right" }, thickness: 12, len: 0.8 },
      symbol: features.map((d) => (d.usage_growth > cap ? "triangle-up" : "circle")),
      opacity: 0.85, line: { color: "#fff", width: 1.5 },
    },
  }];
  const st = params.share_threshold, gt = params.growth_threshold * 100;
  const corner = (x, y, text, color, xa, ya) => ({ xref: "paper", yref: "paper", x, y, text, showarrow: false, xanchor: xa, yanchor: ya, font: { size: 13, color }, bgcolor: "rgba(255,255,255,.75)" });
  const layout = base({
    height,
    xaxis: { type: "log", title: { text: "Relative adoption share (vs portfolio median, log) →" }, gridcolor: GRID, autorange: "reversed" },
    yaxis: { title: { text: `Usage growth, last ${params.lookback_months} months (%)` }, gridcolor: GRID, zeroline: true, zerolinecolor: "#cbd5e1", range: [-45, cap * 100 + 12], ticksuffix: "%" },
    shapes: [
      { type: "line", xref: "x", yref: "paper", x0: st, x1: st, y0: 0, y1: 1, line: { color: "#94a3b8", dash: "dot", width: 1.5 } },
      { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: gt, y1: gt, line: { color: "#94a3b8", dash: "dot", width: 1.5 } },
    ],
    annotations: [
      corner(0.01, 0.99, "<b>★ STARS</b>", "#1d4ed8", "left", "top"),
      corner(0.99, 0.99, "<b>? QUESTION MARKS</b>", "#b45309", "right", "top"),
      corner(0.01, 0.01, "<b>$ CASH COWS</b>", "#047857", "left", "bottom"),
      corner(0.99, 0.01, "<b>✕ DOGS</b>", "#b91c1c", "right", "bottom"),
    ],
  });
  render(el, data, layout, onClick);
}

// ---------------------------------------------------------------------------
export function donut(el, labels, values, colors, height = 260) {
  const keep = values.map((v, i) => i).filter((i) => values[i] > 0);
  [labels, values, colors] = [keep.map((i) => labels[i]), keep.map((i) => values[i]), keep.map((i) => colors[i])];
  const data = [{ type: "pie", hole: 0.62, labels, values, marker: { colors, line: { color: "#fff", width: 2 } }, textinfo: "value", sort: false, hovertemplate: "%{label}: %{value} (%{percent})<extra></extra>" }];
  if (window.Plotly) { window.Plotly.react(el, data, base({ height, margin: { l: 10, r: 10, t: 10, b: 10 }, showlegend: true, legend: { orientation: "v", x: 1.02, y: 0.5 } }), { ...CONFIG, displayModeBar: false }); return; }
  render(el, data, base({ height, margin: { l: 10, r: 10, t: 10, b: 10 }, showlegend: true, legend: { orientation: "v", x: 1.02, y: 0.5 } }));
}

// ---------------------------------------------------------------------------
export function moduleBars(el, modules, height = 300) {
  const m = [...modules].sort((a, b) => b.revenue - a.revenue);
  const data = [
    { type: "bar", name: "Attributed revenue / mo", x: m.map((d) => d.module), y: m.map((d) => d.revenue / 1e5), marker: { color: "#4f46e5" }, customdata: m.map((d) => inr(d.revenue)), hovertemplate: "%{x}<br>Revenue %{customdata}<extra></extra>" },
    { type: "bar", name: "Maintenance cost / mo", x: m.map((d) => d.module), y: m.map((d) => d.eng_cost / 1e5), marker: { color: "#f97316" }, customdata: m.map((d) => [inr(d.eng_cost), d.traps]), hovertemplate: "%{x}<br>Eng cost %{customdata[0]} · %{customdata[1]} traps<extra></extra>" },
  ];
  render(el, data, base({ height, barmode: "group", bargap: 0.3, yaxis: { gridcolor: GRID, title: { text: "₹ lakh / month" } }, margin: { l: 56, r: 10, t: 10, b: 70 } }));
}

// ---------------------------------------------------------------------------
const plcCurve = (x) => {
  // stylised sales curve over x∈[0,100]
  const rise = 1 / (1 + Math.exp(-(x - 32) / 7));
  const fall = x > 70 ? Math.exp(-((x - 70) ** 2) / 520) : 1;
  return 100 * rise * fall;
};
const STAGE_BANDS = { Introduction: [2, 22], Growth: [24, 50], Maturity: [52, 74], Decline: [76, 98] };

export function lifecycleCurve(el, features, onClick, height = 460) {
  const xs = [...Array(101).keys()];
  const data = [{ type: "scatter", mode: "lines", x: xs, y: xs.map(plcCurve), line: { color: "#c7d2fe", width: 5, shape: "spline" }, hoverinfo: "skip", showlegend: false }];
  const size = sizeScale(features.map((d) => d.monthly_revenue_inr), 10, 34);
  const byStage = groupBy(features, "plc_stage");
  Object.entries(STAGE_BANDS).forEach(([stage]) => {
    const pts = (byStage.get(stage) || []).slice();
    // order inside each band: earlier = younger / faster-growing
    pts.sort((a, b) => (stage === "Introduction" ? a.age_months - b.age_months : stage === "Decline" ? b.usage_growth - a.usage_growth : b.usage_growth - a.usage_growth));
    const [lo, hi] = STAGE_BANDS[stage];
    pts.forEach((d, i) => { d._x = pts.length === 1 ? (lo + hi) / 2 : lo + (i / (pts.length - 1)) * (hi - lo); });
  });
  ORDER.action.forEach((a) => {
    const pts = features.filter((d) => d.action === a && d._x !== undefined);
    if (!pts.length) return;
    data.push({
      type: "scatter", mode: "markers", name: a, x: pts.map((d) => d._x), y: pts.map((d) => plcCurve(d._x)),
      text: pts.map((d) => d.feature_name), customdata: pts.map(featCustom), hovertemplate: hoverFeature,
      marker: { size: pts.map((d) => size(d.monthly_revenue_inr)), color: COLORS.action[a], opacity: 0.88, line: { color: "#fff", width: 1.5 } },
    });
  });
  const shapes = Object.entries(STAGE_BANDS).map(([s, [lo, hi]], i) => ({ type: "rect", layer: "below", xref: "x", yref: "paper", x0: lo - 1, x1: hi + 1, y0: 0, y1: 1, fillcolor: i % 2 ? "rgba(99,102,241,.035)" : "rgba(99,102,241,.07)", line: { width: 0 } }));
  const annotations = Object.entries(STAGE_BANDS).map(([s, [lo, hi]]) => ({ x: (lo + hi) / 2, y: 1.02, xref: "x", yref: "paper", text: `<b>${s.toUpperCase()}</b> · ${(byStage.get(s) || []).length}`, showarrow: false, font: { size: 12, color: COLORS.plc[s] } }));
  render(el, data, base({ height, shapes, annotations, margin: { l: 40, r: 20, t: 36, b: 40 }, xaxis: { visible: false, range: [0, 100] }, yaxis: { title: { text: "Adoption / revenue (stylised)" }, showticklabels: false, gridcolor: GRID, range: [-5, 115] } }), onClick);
}

// ---------------------------------------------------------------------------
export function usageHeatmap(el, rows, months, height) {
  const data = [{
    type: "heatmap", x: months, y: rows.map((r) => r.name), z: rows.map((r) => r.values),
    colorscale: [[0, "#f8fafc"], [0.35, "#c7d2fe"], [0.7, "#6366f1"], [1, "#312e81"]], zmin: 0, zmax: 1,
    colorbar: { title: { text: "% of peak" }, tickformat: ".0%", thickness: 12 },
    hovertemplate: "%{y}<br>%{x}: %{z:.0%} of peak<extra></extra>", xgap: 1, ygap: 1,
  }];
  render(el, data, base({ height: height || Math.max(360, rows.length * 17 + 80), margin: { l: 200, r: 20, t: 10, b: 60 }, yaxis: { autorange: "reversed", tickfont: { size: 11 } } }));
}

// ---------------------------------------------------------------------------
export function semanticMap(el, map, colorBy = "cluster", height = 520) {
  const key = colorBy === "category" ? map.category : map.cluster;
  const groups = new Map();
  key.forEach((k, i) => { if (!groups.has(k)) groups.set(k, []); groups.get(k).push(i); });
  const palette = ["#4f46e5", "#0891b2", "#059669", "#d97706", "#db2777", "#7c3aed", "#dc2626", "#0f766e", "#ca8a04", "#2563eb", "#9333ea", "#ea580c", "#16a34a", "#e11d48", "#0284c7", "#65a30d", "#475569", "#a16207"];
  const data = [...groups.entries()].sort((a, b) => b[1].length - a[1].length).map(([k, idx], i) => ({
    type: "scattergl", mode: "markers", name: `${k} (${idx.length})`,
    x: idx.map((i2) => map.x[i2]), y: idx.map((i2) => map.y[i2]),
    text: idx.map((i2) => `<b>${map.feature[i2]}</b><br>${map.text[i2]}<br><i>${map.category[i2]}</i> · sentiment ${map.sentiment[i2].toFixed(2)}`),
    hovertemplate: "%{text}<extra></extra>",
    marker: { size: 6, opacity: 0.75, color: colorBy === "category" ? COLORS.category[k] : palette[i % palette.length] },
  }));
  render(el, data, base({ height, xaxis: { visible: false }, yaxis: { visible: false }, margin: { l: 10, r: 10, t: 10, b: 10 }, legend: { orientation: "v", x: 1.01, y: 1, font: { size: 11 } } }));
}

// ---------------------------------------------------------------------------
export function categoryHeatmap(el, hm, topN = 22) {
  const order = ["Core Utility", "UX Friction", "Performance Issue", "Feature Bloat Indicator"];
  const cols = order.filter((c) => hm.categories.includes(c));
  const idx = cols.map((c) => hm.categories.indexOf(c));
  const feats = hm.features.slice(0, topN);
  const z = hm.z.slice(0, topN).map((row) => { const s = row.reduce((a, b) => a + b, 0) || 1; return idx.map((i) => row[i] / s); });
  const raw = hm.z.slice(0, topN).map((row) => idx.map((i) => row[i]));
  const data = [{
    type: "heatmap", x: cols, y: feats, z, customdata: raw, colorscale: [[0, "#f8fafc"], [0.5, "#a5b4fc"], [1, "#3730a3"]], zmin: 0, zmax: 0.8,
    hovertemplate: "%{y}<br>%{x}: %{customdata} tickets (%{z:.0%})<extra></extra>", xgap: 2, ygap: 2,
    colorbar: { tickformat: ".0%", thickness: 12, title: { text: "share" } },
    text: raw, texttemplate: "%{text}", textfont: { size: 10 },
  }];
  render(el, data, base({ height: Math.max(380, feats.length * 22 + 110), margin: { l: 200, r: 10, t: 10, b: 90 }, yaxis: { autorange: "reversed", tickfont: { size: 11 } } }));
}

// ---------------------------------------------------------------------------
export function featureTrend(el, usage, engineering, height = 280) {
  const data = [
    { type: "scatter", mode: "lines", name: "Active users", x: usage.map((d) => d.month), y: usage.map((d) => d.active_users), line: { color: "#4f46e5", width: 3, shape: "spline" }, fill: "tozeroy", fillcolor: "rgba(79,70,229,.08)" },
    { type: "bar", name: "Maintenance hrs", x: engineering.map((d) => d.month), y: engineering.map((d) => d.maintenance_hours), yaxis: "y2", marker: { color: "rgba(249,115,22,.45)" } },
  ];
  render(el, data, base({ height, margin: { l: 50, r: 50, t: 10, b: 40 }, yaxis: { title: { text: "Active users" }, gridcolor: GRID, rangemode: "tozero" }, yaxis2: { title: { text: "Eng hours" }, overlaying: "y", side: "right", showgrid: false, rangemode: "tozero" }, legend: { orientation: "h", y: 1.12, x: 0 } }));
}

export function kScores(el, scores, chosen, height = 200) {
  const ks = Object.keys(scores).map(Number).sort((a, b) => a - b);
  if (!ks.length) { el.innerHTML = '<div class="muted small">k fixed – no sweep.</div>'; return; }
  const data = [{ type: "scatter", mode: "lines+markers", x: ks, y: ks.map((k) => scores[k]), line: { color: "#4f46e5" }, marker: { size: ks.map((k) => (k === chosen ? 13 : 7)), color: ks.map((k) => (k === chosen ? "#dc2626" : "#4f46e5")) }, hovertemplate: "k=%{x}: silhouette %{y:.3f}<extra></extra>" }];
  render(el, data, base({ height, margin: { l: 50, r: 10, t: 10, b: 40 }, xaxis: { title: { text: "k (clusters)" }, dtick: 1, gridcolor: GRID }, yaxis: { title: { text: "silhouette" }, gridcolor: GRID } }));
}
