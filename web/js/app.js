// App shell: state, routing, assumptions drawer, feature drawer, pipeline polling.
import { $, $$, api, qs, esc, inr, pct, spct, num, badge, catBadge, openDrawer, closeDrawer, toast, debounce, COLORS } from "./ui.js";
import * as charts from "./charts.js";
import { VIEWS } from "./views.js";

const LS_KEY = "cc_params_v1";

export const state = {
  view: "overview",
  params: null,
  defaults: null,
  analysis: null,
  status: null,
  version: -1,
  cache: {}, // per-version cached payloads (clusters, map, heatmap, memo)
  ui: {}, // per-view UI state (filters, sort, selections)
};

// ---------------------------------------------------------------- data
export async function loadAnalysis() {
  state.analysis = await api(`/api/analysis?${qs(state.params)}`);
  state.cache.memo = null;
  $("#dataset-chip").textContent = state.status?.dataset?.name || "—";
}

export async function cached(key, path) {
  if (!state.cache[key]) state.cache[key] = await api(path);
  return state.cache[key];
}

export const ctx = {
  state,
  openFeature,
  rerender: () => renderView(),
  cached,
  paramsQS: () => qs(state.params),
  startedRun: () => pollStatus(true),
};

// ---------------------------------------------------------------- routing
const TITLES = {
  overview: ["Executive Overview", "Where engineering capacity goes versus where revenue comes from — and which features are complexity traps."],
  matrix: ["Complexity Trap Matrix", "Every feature plotted by its composite Complexity Index against its ROI Index. Bottom-right = high cost, low return."],
  bcg: ["BCG Portfolio Matrix", "Classic growth-share matrix adapted to a product portfolio: relative adoption share vs usage growth. Bubble size = revenue, colour = complexity."],
  plc: ["Product Lifecycle", "Each feature placed on the Introduction → Growth → Maturity → Decline curve from its usage trajectory."],
  feedback: ["Feedback Intelligence", "Unstructured tickets & reviews mined with embeddings, semantic clustering and LLM labelling into strategic signal."],
  portfolio: ["Portfolio & Scenarios", "The full feature ledger. Select features to simulate a sunset decision and see the capacity and P&L impact."],
  data: ["Data & Pipeline", "Upload your own catalog / feedback exports, regenerate synthetic data, and inspect how the AI pipeline ran."],
};

async function renderView() {
  const root = $("#view");
  const [title, sub] = TITLES[state.view];
  $("#view-title").textContent = title;
  $("#view-subtitle").textContent = sub;
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === state.view));
  if (!state.analysis && state.view !== "data") {
    root.innerHTML = '<div class="card empty">Waiting for the analysis pipeline…</div>';
    return;
  }
  try {
    await VIEWS[state.view](root, ctx);
  } catch (e) {
    console.error(e);
    root.innerHTML = `<div class="card err">Failed to render view: ${esc(e.message)}</div>`;
  }
}

function route() {
  const v = (location.hash || "#overview").slice(1);
  state.view = VIEWS[v] ? v : "overview";
  renderView();
  window.scrollTo({ top: 0 });
}

// ---------------------------------------------------------------- assumptions drawer
const FIELDS = [
  { group: "Complexity Index weights" },
  { key: "w_maintenance", label: "Maintenance hours", min: 0, max: 1, step: 0.05, fmt: (v) => v.toFixed(2), hint: "Avg monthly engineering hours spent keeping the feature alive" },
  { key: "w_bugs", label: "Bug-ticket frequency", min: 0, max: 1, step: 0.05, fmt: (v) => v.toFixed(2), hint: "Avg monthly bug tickets from Jira / GitHub" },
  { key: "w_friction", label: "Feedback friction", min: 0, max: 1, step: 0.05, fmt: (v) => v.toFixed(2), hint: "UX + performance complaints per month (from AI-mined feedback)" },
  { group: "ROI Index weights" },
  { key: "w_revenue", label: "Adoption × revenue", min: 0, max: 1, step: 0.05, fmt: (v) => v.toFixed(2), hint: "Adoption rate multiplied by directly attributed revenue" },
  { key: "w_enterprise", label: "Enterprise dependency", min: 0, max: 1, step: 0.05, fmt: (v) => v.toFixed(2), hint: "Number of enterprise clients relying on the feature (tier dependency)" },
  { group: "Complexity-trap thresholds" },
  { key: "complexity_threshold", label: "High-complexity cut-off", min: 10, max: 90, step: 1, fmt: (v) => v.toFixed(0) },
  { key: "roi_threshold", label: "Low-ROI cut-off", min: 10, max: 90, step: 1, fmt: (v) => v.toFixed(0) },
  { group: "BCG & lifecycle" },
  { key: "growth_threshold", label: "High-growth cut-off", min: -0.2, max: 0.5, step: 0.01, fmt: (v) => spct(v), hint: "Usage growth over the lookback window (classic BCG uses 10%)" },
  { key: "share_threshold", label: "High relative-share cut-off", min: 0.25, max: 3, step: 0.05, fmt: (v) => `${v.toFixed(2)}×`, hint: "Adoption relative to the portfolio median (classic BCG uses 1.0×)" },
  { key: "lookback_months", label: "Lookback window", min: 3, max: 12, step: 1, fmt: (v) => `${v} mo` },
  { group: "Economics" },
  { key: "hourly_rate_inr", label: "Loaded engineering cost / hour", min: 500, max: 10000, step: 100, fmt: (v) => `₹${num(v)}` },
];

function renderAssumptions() {
  const p = state.params;
  const body = $("#assump-body");
  body.innerHTML = FIELDS.map((f) => f.group
    ? `<div class="group-title">${f.group}</div>`
    : `<div class="field"><div class="field-row"><label for="p-${f.key}">${f.label}</label><span class="val" id="v-${f.key}">${f.fmt(p[f.key])}</span></div>
       <input type="range" id="p-${f.key}" data-key="${f.key}" min="${f.min}" max="${f.max}" step="${f.step}" value="${p[f.key]}" />
       ${f.hint ? `<div class="hint">${f.hint}</div>` : ""}</div>`).join("") + `
    <div class="field"><div class="field-row"><label for="p-normalization">Normalisation</label></div>
      <select id="p-normalization"><option value="percentile">Percentile rank (robust)</option><option value="minmax">Min-max on log scale</option></select>
      <div class="hint">How raw metrics are scaled to 0–100 before weighting.</div></div>
    <div class="formula" id="formula"></div>
    <div style="display:flex;gap:8px"><button class="btn" id="btn-reset">Reset to defaults</button></div>`;
  $("#p-normalization").value = p.normalization;
  const apply = debounce(async () => {
    localStorage.setItem(LS_KEY, JSON.stringify(state.params));
    await loadAnalysis();
    renderView();
  }, 220);
  $$("input[type=range]", body).forEach((inp) => inp.addEventListener("input", () => {
    const f = FIELDS.find((x) => x.key === inp.dataset.key);
    state.params[f.key] = Number(inp.value);
    $(`#v-${f.key}`).textContent = f.fmt(Number(inp.value));
    renderFormula();
    apply();
  }));
  $("#p-normalization").addEventListener("change", (e) => { state.params.normalization = e.target.value; apply(); });
  $("#btn-reset").addEventListener("click", () => { state.params = { ...state.defaults }; renderAssumptions(); apply(); });
  renderFormula();
}

function renderFormula() {
  const p = state.params;
  const cw = p.w_maintenance + p.w_bugs + p.w_friction || 1;
  const rw = p.w_revenue + p.w_enterprise || 1;
  $("#formula").innerHTML =
    `Complexity = ${(p.w_maintenance / cw).toFixed(2)}·N(hours) + ${(p.w_bugs / cw).toFixed(2)}·N(bugs) + ${(p.w_friction / cw).toFixed(2)}·N(friction)<br>` +
    `ROI = ${(p.w_revenue / rw).toFixed(2)}·N(adoption × revenue) + ${(p.w_enterprise / rw).toFixed(2)}·N(enterprise clients)<br>` +
    `Trap ⇔ Complexity ≥ ${p.complexity_threshold} and ROI &lt; ${p.roi_threshold}`;
}

// ---------------------------------------------------------------- feature drawer
async function openFeature(id) {
  openDrawer("feat");
  $("#feat-head").innerHTML = '<div class="muted">Loading…</div><button class="icon-btn" data-close>✕</button>';
  $("#feat-body").innerHTML = "";
  let d;
  try {
    d = await api(`/api/features/${encodeURIComponent(id)}?${qs(state.params)}`);
  } catch (e) {
    $("#feat-body").innerHTML = `<div class="err">${esc(e.message)}</div>`;
    return;
  }
  const f = d.feature;
  const p = state.params;
  $("#feat-head").innerHTML = `
    <div>
      <div class="muted small">${esc(f.module)} · ${esc(f.tier)} tier · released ${esc(f.release_date || "–")}${f.age_months != null ? ` (${Math.round(f.age_months)} mo)` : ""}</div>
      <h2 style="margin:4px 0 8px">${esc(f.feature_name)}</h2>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${badge(f.action)} ${f.is_complexity_trap ? badge("Complexity Trap", "b-trap") : badge(f.quadrant, "b-Monitor plain")}
        ${badge("BCG: " + f.bcg, "b-Monitor plain")} ${badge("PLC: " + f.plc_stage, "b-Monitor plain")} ${badge(f.confidence + " confidence", "b-" + f.confidence + " plain")}
      </div>
    </div>
    <button class="icon-btn" data-close>✕</button>`;
  const comp = (label, v, w, color) => `<div class="comp-row"><span>${label} <span class="muted tiny">w ${w.toFixed(2)}</span></span><div class="comp-track"><span style="width:${v}%;background:${color}"></span></div><b class="num">${Math.round(v)}</b></div>`;
  const k = (label, value, cls = "") => `<div class="card kpi" style="padding:12px 14px"><div class="label">${label}</div><div class="value ${cls}" style="font-size:19px">${value}</div></div>`;
  $("#feat-body").innerHTML = `
    <div class="rationale"><b>${esc(f.action)}:</b> ${esc(f.rationale)}</div>
    <div class="grid g4">
      ${k("Eng cost / mo", inr(f.eng_cost_monthly))}
      ${k("Revenue / mo", inr(f.monthly_revenue_inr))}
      ${k("Net / mo", inr(f.net_contribution_monthly), f.net_contribution_monthly < 0 ? "neg" : "pos")}
      ${k("Cost : revenue", f.cost_to_revenue == null ? "∞" : f.cost_to_revenue.toFixed(2) + "×")}
      ${k("Adoption", pct(f.adoption_rate, 1))}
      ${k("Usage growth", spct(f.usage_growth), f.usage_growth < 0 ? "neg" : "pos")}
      ${k("Bugs / mo", num(f.bug_tickets, 1))}
      ${k("Sentiment", (f.avg_sentiment >= 0 ? "+" : "") + num(f.avg_sentiment, 2), f.avg_sentiment < 0 ? "neg" : "pos")}
    </div>
    <div class="grid g2">
      <div class="card"><div class="card-head"><div><h3>Complexity Index · ${Math.round(f.complexity_index)}</h3><div class="muted">Normalised components (0–100)</div></div></div>
        ${comp("Maintenance hours", f.c_maintenance, p.w_maintenance, "#f97316")}
        ${comp("Bug frequency", f.c_bugs, p.w_bugs, "#ef4444")}
        ${comp("Feedback friction", f.c_friction, p.w_friction, "#f59e0b")}
        <div class="muted small" style="margin-top:8px">${num(f.maintenance_hours)} hrs/mo · ${num(f.bug_tickets, 1)} bugs/mo · ${num(f.friction_per_month, 1)} friction tickets/mo</div>
      </div>
      <div class="card"><div class="card-head"><div><h3>ROI Index · ${Math.round(f.roi_index)}</h3><div class="muted">Normalised components (0–100)</div></div></div>
        ${comp("Adoption × revenue", f.r_revenue, p.w_revenue, "#4f46e5")}
        ${comp("Enterprise reliance", f.r_enterprise, p.w_enterprise, "#0891b2")}
        <div class="muted small" style="margin-top:8px">${num(f.active_users)} active of ${num(f.eligible_users)} eligible · ${num(f.enterprise_clients)} enterprise clients</div>
      </div>
    </div>
    <div class="card"><div class="card-head"><div><h3>Usage vs maintenance effort</h3><div class="muted">Monthly active users (line) and engineering hours (bars)</div></div></div><div id="feat-trend" class="plot"></div></div>
    <div class="grid g2">
      <div class="card"><div class="card-head"><div><h3>Feedback themes</h3><div class="muted">${num(f.tickets)} tickets · top theme: ${esc(f.top_theme)}</div></div></div>
        ${d.themes.length ? `<table><tbody>${d.themes.map((t) => `<tr><td class="wrap">${esc(t.cluster_name)}</td><td class="r num">${t.count}</td><td class="r num ${t.sentiment < 0 ? "neg" : "pos"}">${t.sentiment.toFixed(2)}</td></tr>`).join("")}</tbody></table>` : '<div class="muted">No tickets.</div>'}
      </div>
      <div class="card"><div class="card-head"><div><h3>Voice of customer</h3><div class="muted">Most negative & most positive</div></div></div>
        ${d.quotes.map((q) => `<div style="margin-bottom:10px"><div style="line-height:1.45">“${esc(q.text)}”</div><div class="tiny muted" style="margin-top:3px">${catBadge(q.category)} · ${esc(q.source)} · ${String(q.created_at || "").slice(0, 10)}</div></div>`).join("") || '<div class="muted">No tickets.</div>'}
      </div>
    </div>`;
  charts.featureTrend($("#feat-trend"), d.usage, d.engineering);
}

// ---------------------------------------------------------------- pipeline polling
let polling = false;
async function pollStatus(force = false) {
  if (polling && !force) return;
  polling = true;
  const badgeEl = $("#pipeline-badge");
  try {
    while (true) {
      let s;
      try { s = await api("/api/status"); } catch (e) { await sleep(1500); continue; }
      state.status = s;
      badgeEl.className = "sidebar-foot " + (s.status === "ready" ? "ready" : s.status === "error" ? "error" : "");
      const llm = s.llm ? `${s.llm.provider}${s.llm.enabled ? " · " + s.llm.model : ""}` : "";
      $(".pb-title", badgeEl).textContent = s.status === "ready" ? "Pipeline ready" : s.status === "error" ? "Pipeline error" : "Pipeline running";
      $(".pb-sub", badgeEl).textContent = s.status === "running" ? s.stage : s.status === "error" ? s.error : `LLM: ${llm} · ${s.nlp?.embedding_backend || ""}`;
      const running = s.status === "running";
      $("#overlay").classList.toggle("show", running);
      $("#overlay-stage").textContent = s.stage || "";
      if (s.status === "error") toast(`Pipeline error: ${s.error}`);
      if (!running && s.version !== state.version && s.dataset) {
        state.version = s.version;
        state.cache = {};
        await loadAnalysis();
        renderView();
        if (s.version > 1) toast("Analysis refreshed with new dataset");
      }
      if (!running) break;
      await sleep(1200);
    }
  } finally {
    polling = false;
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- boot
async function boot() {
  const d = await api("/api/params/defaults");
  state.defaults = d.defaults;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch (_) { /* ignore */ }
  state.params = { ...d.defaults, ...Object.fromEntries(Object.entries(saved).filter(([k]) => k in d.defaults)) };
  renderAssumptions();

  $("#btn-assumptions").addEventListener("click", () => openDrawer("assump"));
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) { closeDrawer("assump"); closeDrawer("feat"); }
  });
  $("#assump-backdrop").addEventListener("click", () => closeDrawer("assump"));
  $("#feat-backdrop").addEventListener("click", () => closeDrawer("feat"));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer("assump"); closeDrawer("feat"); } });
  $$("#nav a").forEach((a) => a.addEventListener("click", () => { location.hash = a.dataset.view; }));
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", debounce(() => $$(".js-plotly-plot").forEach((el) => window.Plotly?.Plots.resize(el)), 200));

  route();
  await pollStatus(true);
}

// Wait for deferred Plotly before booting.
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();

export { COLORS };
