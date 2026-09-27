// View renderers. Each receives (root, ctx) and paints the page.
import { $, $$, api, qs, esc, inr, pct, spct, num, badge, catBadge, miniBar, markdown, toast, debounce, COLORS } from "./ui.js";
import * as charts from "./charts.js";

const card = (title, sub, body, extra = "", id = "") =>
  `<div class="card" ${id ? `id="${id}"` : ""}><div class="card-head"><div><h3>${title}</h3>${sub ? `<div class="muted">${sub}</div>` : ""}</div>${extra}</div>${body}</div>`;
const kpi = (label, value, foot, accent = "") =>
  `<div class="card kpi ${accent}"><div class="label">${label}</div><div class="value">${value}</div><div class="foot">${foot}</div></div>`;

function featureCell(f) {
  return `<div class="fname">${esc(f.feature_name)}</div><div class="fmod">${esc(f.module)}</div>`;
}
function bindRowClicks(root, ctx) {
  $$("tr[data-fid]", root).forEach((tr) => tr.addEventListener("click", (e) => {
    if (e.target.closest("input,button,a")) return;
    ctx.openFeature(tr.dataset.fid);
  }));
}

// ===========================================================================
// OVERVIEW
// ===========================================================================
async function overview(root, ctx) {
  const { summary: s, features } = ctx.state.analysis;
  const sun = s.sunset;
  const quads = ["Complexity Trap", "Strategic Heavyweight", "Efficient Core", "Low-Cost Long Tail"];
  const share = (key) => {
    const tot = features.reduce((a, f) => a + (key === "count" ? 1 : f[key]), 0) || 1;
    return quads.map((q) => ({ q, v: features.filter((f) => f.quadrant === q).reduce((a, f) => a + (key === "count" ? 1 : f[key]), 0) / tot }));
  };
  const splitRow = (label, parts) => `<div class="split-row"><div class="lbl">${label}</div><div class="split-bar">${parts.map((p) =>
    `<div style="width:${(p.v * 100).toFixed(2)}%;background:${COLORS.quadrant[p.q]}" title="${p.q}: ${pct(p.v, 1)}">${p.v > 0.07 ? pct(p.v) : ""}</div>`).join("")}</div></div>`;

  const traps = features.filter((f) => f.is_complexity_trap).sort((a, b) => b.trap_score - a.trap_score);

  root.innerHTML = `
    <div class="grid g5">
      ${kpi("Attributed revenue", `${inr(s.total_revenue_monthly)}<span class="muted small"> /mo</span>`, `Net of maintenance: <b>${inr(s.net_contribution_monthly)}</b>/mo`, "accent-violet")}
      ${kpi("Maintenance cost", `${inr(s.total_eng_cost_monthly)}<span class="muted small"> /mo</span>`, `${num(s.total_eng_hours_monthly)} hrs · ${s.engineering_fte} FTE · ${pct(s.eng_cost_to_revenue)} of revenue`, "accent-amber")}
      ${kpi("Complexity tax", `${inr(s.complexity_tax_annual)}<span class="muted small"> /yr</span>`, `Spent maintaining <b>${s.n_traps}</b> complexity traps`, "accent-red")}
      ${kpi("Capacity locked in traps", pct(s.trap_hours_share), `${s.trap_fte} FTE for just <b>${pct(s.trap_revenue_share, 1)}</b> of revenue`, "accent-red")}
      ${kpi("Sunset net impact", `${inr(sun.net_annual_impact)}<span class="muted small"> /yr</span>`, `${sun.count} sunsets free ${sun.fte_freed} FTE · ${inr(sun.revenue_at_risk_annual)} rev. at risk`, "accent-green")}
    </div>

    <div class="grid g-3-2">
      ${card("Capacity vs. return by strategic quadrant", "Share of engineering hours, attributed revenue and feature count falling in each Complexity-ROI quadrant",
        `${splitRow("Engineering hours", share("maintenance_hours"))}
         ${splitRow("Revenue", share("monthly_revenue_inr"))}
         ${splitRow("Features", share("count"))}
         <div class="legend" style="margin-top:12px">${quads.map((q) => `<span><i style="background:${COLORS.quadrant[q]}"></i>${q} (${s.quadrants[q]})</span>`).join("")}</div>
         <div class="muted small" style="margin-top:14px;line-height:1.55">
           <b>Pareto check:</b> the top 20% of features generate <b>${pct(s.pareto.top20_revenue_share)}</b> of revenue, while features with below-median ROI consume <b>${pct(s.pareto.low_roi_hours_share)}</b> of maintenance hours.
         </div>`)}
      ${card("Recommended actions", "Portfolio decision mix", '<div id="ov-donut"></div>')}
    </div>

    <div class="grid g-3-2">
      ${card("Top complexity traps", "High complexity, low ROI — ranked by trap score. Click a row for the full diagnosis.",
        `<div class="table-wrap"><table><thead><tr><th>Feature</th><th class="r">Complexity</th><th class="r">ROI</th><th class="r">Eng cost/mo</th><th class="r">Revenue/mo</th><th>Action</th></tr></thead><tbody>
        ${traps.slice(0, 10).map((f) => `<tr class="clickable" data-fid="${f.feature_id}"><td>${featureCell(f)}</td>
          <td class="r num">${miniBar(f.complexity_index, 100, "#dc2626")}${f.complexity_index.toFixed(0)}</td>
          <td class="r num">${f.roi_index.toFixed(0)}</td><td class="r num">${inr(f.eng_cost_monthly)}</td><td class="r num">${inr(f.monthly_revenue_inr)}</td>
          <td>${badge(f.action)}</td></tr>`).join("") || '<tr><td colspan="6" class="empty">No complexity traps at the current thresholds 🎉</td></tr>'}
        </tbody></table></div>`)}
      ${card("Executive memo", '<span id="memo-src">generating…</span>', '<div class="memo" id="memo">Generating…</div>',
        `<a class="btn ghost" href="/api/export/memo.md?${ctx.paramsQS()}" download>⤓ .md</a>`)}
    </div>

    ${card("Module P&amp;L: revenue vs maintenance cost", "Monthly attributed revenue against engineering maintenance cost per product area", '<div id="ov-modules"></div>')}
  `;
  const acts = ["Invest", "Retain", "Refactor", "Monitor", "Sunset"];
  charts.donut($("#ov-donut"), acts, acts.map((a) => s.actions[a]), acts.map((a) => COLORS.action[a]), 290);
  charts.moduleBars($("#ov-modules"), s.modules);
  bindRowClicks(root, ctx);

  try {
    const key = `memo:${ctx.paramsQS()}`;
    const m = await ctx.cached(key, `/api/memo?${ctx.paramsQS()}`);
    if (!$("#memo")) return;
    $("#memo").innerHTML = markdown(m.markdown);
    $("#memo-src").textContent = m.source === "template" ? "Rule-based narrative (connect an LLM for AI-written memos)" : `Written by ${m.source}`;
  } catch (e) {
    if ($("#memo")) $("#memo").innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

// ===========================================================================
// COMPLEXITY MATRIX
// ===========================================================================
async function matrix(root, ctx) {
  const { features, summary } = ctx.state.analysis;
  const p = ctx.state.params;
  const ui = (ctx.state.ui.matrix ||= { colorBy: "action", sizeBy: "eng_cost_monthly", labels: true });
  const traps = features.filter((f) => f.is_complexity_trap).sort((a, b) => b.trap_score - a.trap_score);
  root.innerHTML = `
    ${card("Complexity cost vs. return", `${summary.n_traps} complexity traps flagged · thresholds C ≥ ${p.complexity_threshold}, ROI &lt; ${p.roi_threshold} (tune in Model assumptions)`,
      '<div id="mx-chart" class="plot"></div>',
      `<div class="toolbar">
        <label class="small muted">Colour</label><select id="mx-color"><option value="action">Action</option><option value="quadrant">Quadrant</option><option value="bcg">BCG class</option><option value="plc_stage">Lifecycle stage</option><option value="module">Module</option></select>
        <label class="small muted">Size</label><select id="mx-size"><option value="eng_cost_monthly">Eng cost</option><option value="monthly_revenue_inr">Revenue</option><option value="active_users">Active users</option><option value="tickets">Tickets</option></select>
        <label class="small"><input type="checkbox" id="mx-labels" ${ui.labels ? "checked" : ""}/> labels</label>
      </div>`)}
    <div class="grid g-3-2">
      ${card("Flagged complexity traps", "Candidates for sunsetting or refactoring",
        `<div class="table-wrap" style="max-height:420px"><table><thead><tr><th>Feature</th><th class="r">Trap score</th><th class="r">Hrs/mo</th><th class="r">Bugs/mo</th><th class="r">Bloat share</th><th class="r">Cost : rev</th><th>Action</th></tr></thead><tbody>
        ${traps.map((f) => `<tr class="clickable" data-fid="${f.feature_id}"><td>${featureCell(f)}</td><td class="r num"><b>${f.trap_score.toFixed(0)}</b></td>
          <td class="r num">${num(f.maintenance_hours)}</td><td class="r num">${num(f.bug_tickets, 1)}</td><td class="r num">${pct(f.bloat_share)}</td>
          <td class="r num">${f.cost_to_revenue == null ? "∞" : f.cost_to_revenue.toFixed(1) + "×"}</td><td>${badge(f.action)}</td></tr>`).join("") || '<tr><td colspan="7" class="empty">None at current thresholds.</td></tr>'}
        </tbody></table></div>`)}
      ${card("How the indices are computed", "Composite, normalised 0–100 scores",
        `<div class="formula" style="margin-bottom:12px">Complexity Index = N( maintenance hours ⊕ bug-ticket frequency ⊕ feedback friction )<br>ROI Index = N( adoption rate × attributed revenue ⊕ enterprise dependency )</div>
         <div class="small" style="line-height:1.65;color:var(--ink-2)">
          <b>Maintenance hours</b> and <b>bug tickets</b> come from engineering logs (avg of the last ${p.lookback_months} months).
          <b>Feedback friction</b> is the monthly volume of tickets the AI pipeline labelled <i>UX Friction</i> or <i>Performance Issue</i>.
          <b>Adoption</b> = active ÷ eligible users; <b>enterprise dependency</b> = enterprise accounts using the feature.
          Each metric is ${p.normalization === "percentile" ? "percentile-ranked" : "log-scaled and min-max normalised"} across the portfolio, then weighted.
          A feature is a <b style="color:var(--sunset)">Complexity Trap</b> when it is in the high-cost / low-return quadrant.
         </div>`)}
    </div>`;
  $("#mx-color").value = ui.colorBy;
  $("#mx-size").value = ui.sizeBy;
  const draw = () => charts.complexityMatrix($("#mx-chart"), features, p, ui, ctx.openFeature);
  $("#mx-color").addEventListener("change", (e) => { ui.colorBy = e.target.value; draw(); });
  $("#mx-size").addEventListener("change", (e) => { ui.sizeBy = e.target.value; draw(); });
  $("#mx-labels").addEventListener("change", (e) => { ui.labels = e.target.checked; draw(); });
  draw();
  bindRowClicks(root, ctx);
}

// ===========================================================================
// BCG
// ===========================================================================
const PLAYBOOK = {
  Star: ["#1d4ed8", "Invest to scale", "High adoption share in a fast-growing usage base. Fund roadmap and reliability; they become tomorrow's cash cows."],
  "Cash Cow": ["#047857", "Harvest & protect", "Dominant but slow-growing. Keep stable, minimise new scope, and use the margin to fund Stars and Question Marks."],
  "Question Mark": ["#b45309", "Invest selectively or divest", "Growing fast from a low base. Place bounded bets and set kill criteria — watch their complexity cost closely."],
  Dog: ["#b91c1c", "Divest / sunset", "Low share, low growth. Unless they carry enterprise lock-in, they are prime candidates for deprecation."],
};
async function bcg(root, ctx) {
  const { features, summary } = ctx.state.analysis;
  const p = ctx.state.params;
  root.innerHTML = `
    <div class="grid g-2-1">
      ${card("Growth-share matrix", `Relative share = adoption ÷ portfolio median (cut-off ${p.share_threshold}×) · growth cut-off ${spct(p.growth_threshold)} · ▲ = growth above 60% (clipped) · labels on top-revenue & high-complexity features`, '<div id="bcg-chart" class="plot"></div>')}
      ${card("Strategy playbook", "Classic BCG prescriptions applied to features",
        `<div class="playbook" style="grid-template-columns:1fr">${Object.entries(PLAYBOOK).map(([k, [c, t, d]]) => {
          const list = features.filter((f) => f.bcg === k).sort((a, b) => b.monthly_revenue_inr - a.monthly_revenue_inr);
          const cost = list.reduce((a, f) => a + f.eng_cost_monthly, 0), rev = list.reduce((a, f) => a + f.monthly_revenue_inr, 0);
          return `<div style="border-left:4px solid ${c}"><h4><span style="color:${c}">${k}s · ${summary.bcg[k]}</span><span class="muted small">${t}</span></h4>
            <p>${d}</p><p class="small"><b>${inr(rev)}</b> revenue vs <b>${inr(cost)}</b> eng cost /mo</p>
            <p class="small muted">${list.slice(0, 6).map((f) => `<a data-open="${f.feature_id}">${esc(f.feature_name)}</a>`).join(", ")}${list.length > 6 ? ` +${list.length - 6} more` : ""}</p></div>`;
        }).join("")}</div>`)}
    </div>`;
  charts.bcgMatrix($("#bcg-chart"), features, p, ctx.openFeature, 640);
  $$("[data-open]", root).forEach((a) => a.addEventListener("click", () => ctx.openFeature(a.dataset.open)));
}

// ===========================================================================
// PLC
// ===========================================================================
async function plc(root, ctx) {
  const { features } = ctx.state.analysis;
  const stages = ["Introduction", "Growth", "Maturity", "Decline"];
  const totRev = features.reduce((a, f) => a + f.monthly_revenue_inr, 0) || 1;
  const totHrs = features.reduce((a, f) => a + f.maintenance_hours, 0) || 1;
  const desc = {
    Introduction: "New features still finding fit. Expect high engineering burn while they stabilise.",
    Growth: "Usage accelerating. Scale infrastructure and pricing before competitors catch up.",
    Maturity: "Plateaued adoption. Optimise cost-to-serve and protect margins.",
    Decline: "Usage eroding from peak. Decide: rejuvenate, harvest, or sunset.",
  };
  root.innerHTML = `
    <div class="grid g4">${stages.map((s) => {
      const list = features.filter((f) => f.plc_stage === s);
      const rev = list.reduce((a, f) => a + f.monthly_revenue_inr, 0), hrs = list.reduce((a, f) => a + f.maintenance_hours, 0);
      return `<div class="card kpi" style="border-top:3px solid ${COLORS.plc[s]}"><div class="label">${s}</div><div class="value">${list.length} <span class="muted small">features</span></div>
        <div class="foot">${pct(rev / totRev)} of revenue · ${pct(hrs / totHrs)} of eng hours</div><div class="foot" style="margin-top:8px">${desc[s]}</div></div>`;
    }).join("")}</div>
    ${card("Portfolio on the product lifecycle curve", "Position within each stage is ordered by usage momentum; bubble size = revenue, colour = recommended action", '<div id="plc-chart" class="plot"></div>')}
    ${card("Usage trajectories", "Monthly active users indexed to each feature's own peak — sorted by lifecycle stage", '<div id="plc-heat" class="plot"></div>')}
  `;
  charts.lifecycleCurve($("#plc-chart"), features.map((f) => ({ ...f })), ctx.openFeature);
  const order = { Introduction: 0, Growth: 1, Maturity: 2, Decline: 3 };
  const sorted = [...features].sort((a, b) => order[a.plc_stage] - order[b.plc_stage] || b.usage_growth - a.usage_growth);
  const series = await ctx.cached(`series:${ctx.state.version}`, "/api/series");
  const months = series.months;
  const rows = sorted.map((f) => {
    const s = series.usage[f.feature_id] || {};
    const peak = Math.max(...Object.values(s), 1);
    return { name: `${f.feature_name} · ${f.plc_stage[0]}`, values: months.map((m) => (s[m] == null ? null : s[m] / peak)) };
  });
  charts.usageHeatmap($("#plc-heat"), rows, months);
}

// ===========================================================================
// FEEDBACK
// ===========================================================================
async function feedback(root, ctx) {
  const ui = (ctx.state.ui.feedback ||= { q: "", category: "", feature_id: "", source: "", cluster_id: null, offset: 0, mapColor: "cluster" });
  const [cl, map, hm] = await Promise.all([
    ctx.cached("clusters", "/api/feedback/clusters"),
    ctx.cached("map", "/api/feedback/map"),
    ctx.cached("heatmap", "/api/feedback/heatmap"),
  ]);
  const m = cl.meta;
  const features = ctx.state.analysis.features;
  const cats = ["Core Utility", "UX Friction", "Performance Issue", "Feature Bloat Indicator"];
  const ls = m.label_sources || {};
  const labelStr = Object.entries(ls).map(([k, v]) => `${v} ${k}`).join(" · ");
  const mm = (k, v) => `<div class="m"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  root.innerHTML = `
    <div class="card"><div class="card-head"><div><h3>AI pipeline run</h3><div class="muted">clean → attribute → mask entities → embed → cluster (silhouette-selected k) → LLM label sample → k-NN propagate → name themes</div></div></div>
      <div class="method">
        ${mm("Tickets mined", num(m.n_tickets))}
        ${mm("Themes (k)", `${m.n_clusters} <span class="muted small">silhouette ${m.silhouette}</span>`)}
        ${mm("Embeddings", `${esc(m.embedding_backend)} <span class="muted small">${esc(m.embedding_model)}</span>`)}
        ${mm("Vector index", esc(m.vector_index))}
        ${mm("LLM", m.llm.enabled ? `${esc(m.llm.provider)} · ${esc(m.llm.model)}` : "offline heuristic")}
        ${mm("Labels", esc(labelStr))}
        ${m.llm_heuristic_agreement != null ? mm("LLM ↔ rules agreement", pct(m.llm_heuristic_agreement)) : ""}
        ${mm("Auto-attributed", `${num(m.attribution?.inferred || 0)} tickets <span class="muted small">${num(m.attribution?.unattributed || 0)} platform-level</span>`)}
        ${mm("Runtime", `${m.elapsed_s}s`)}
      </div>
      <div class="legend" style="margin-top:14px">${cats.map((c) => `<span><i style="background:${COLORS.category[c]}"></i>${c}: <b>${num(m.category_counts?.[c] || 0)}</b></span>`).join("")}</div>
    </div>

    ${card("Discovered feedback themes", "Semantic clusters named by the intelligence layer. Click a theme to filter the ticket explorer.",
      `<div class="cluster-grid">${cl.clusters.map((c) => `
        <div class="cluster ${ui.cluster_id === c.cluster_id ? "selected" : ""}" data-cluster="${c.cluster_id}">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start"><h4>${esc(c.name)}</h4><span class="muted small num">${c.size}</span></div>
          <div>${catBadge(c.category)} <span class="small ${c.avg_sentiment < 0 ? "neg" : "pos"}">sentiment ${c.avg_sentiment >= 0 ? "+" : ""}${c.avg_sentiment.toFixed(2)}</span></div>
          <div class="mixbar">${cats.map((k) => `<span style="width:${((c.category_mix[k] || 0) * 100).toFixed(1)}%;background:${COLORS.category[k]}"></span>`).join("")}</div>
          <div class="small muted">${esc(c.summary)}</div>
          ${c.quotes[0] ? `<div class="quote">“${esc(c.quotes[0])}”</div>` : ""}
          <div class="kw">${c.keywords.slice(0, 5).map((k) => `<span>${esc(k)}</span>`).join("")}</div>
          <div class="tiny muted">${esc(c.business_impact || "")}</div>
        </div>`).join("")}</div>`)}

    <div class="grid g2">
      ${card("Semantic map of feedback", "2-D projection (t-SNE) of ticket embeddings", '<div id="fb-map" class="plot"></div>',
        `<select id="fb-mapcolor"><option value="cluster">Colour by theme</option><option value="category">Colour by category</option></select>`)}
      ${card("Feedback mix by feature", "Share of each feature's tickets per category (numbers = ticket counts), top 22 by volume", '<div id="fb-heat" class="plot"></div>')}
    </div>

    ${card("Ticket explorer", '<span id="tk-count"></span>', `
      <div class="toolbar" style="margin-bottom:12px">
        <input type="search" id="tk-q" placeholder="Search text…" value="${esc(ui.q)}" style="min-width:220px" />
        <select id="tk-cat"><option value="">All categories</option>${cats.map((c) => `<option>${c}</option>`).join("")}</select>
        <select id="tk-feat"><option value="">All features</option>${[...features].sort((a, b) => a.feature_name.localeCompare(b.feature_name)).map((f) => `<option value="${f.feature_id}">${esc(f.feature_name)}</option>`).join("")}</select>
        <select id="tk-theme"><option value="">All themes</option>${cl.clusters.map((c) => `<option value="${c.cluster_id}">${esc(c.name)}</option>`).join("")}</select>
        <a class="btn ghost" href="/api/export/tickets.csv" download style="margin-left:auto">⤓ Export mined tickets</a>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Feedback</th><th>Feature</th><th>Category</th><th class="r">Sentiment</th><th>Theme</th><th>Source</th><th>Date</th><th>Label</th></tr></thead><tbody id="tk-body"></tbody></table></div>
      <div class="pager"><span class="muted small" id="tk-page"></span><div class="toolbar"><button class="btn" id="tk-prev">← Prev</button><button class="btn" id="tk-next">Next →</button></div></div>`)}
  `;
  $("#fb-mapcolor").value = ui.mapColor;
  charts.semanticMap($("#fb-map"), map, ui.mapColor);
  charts.categoryHeatmap($("#fb-heat"), hm);
  $("#fb-mapcolor").addEventListener("change", (e) => { ui.mapColor = e.target.value; charts.semanticMap($("#fb-map"), map, ui.mapColor); });

  $("#tk-cat").value = ui.category;
  $("#tk-feat").value = ui.feature_id;
  $("#tk-theme").value = ui.cluster_id ?? "";
  const LIMIT = 25;
  const load = async () => {
    const res = await api(`/api/feedback/tickets?${qs({ q: ui.q, category: ui.category, feature_id: ui.feature_id, cluster_id: ui.cluster_id, limit: LIMIT, offset: ui.offset })}`);
    $("#tk-count").textContent = `${num(res.total)} matching tickets · sorted most negative first`;
    $("#tk-body").innerHTML = res.items.map((t) => `<tr>
      <td class="wrap" style="min-width:320px;max-width:520px">${esc(t.text)}${t.summary ? `<div class="tiny muted">LLM: ${esc(t.summary)}</div>` : ""}</td>
      <td>${t.feature_id ? `<a data-open="${t.feature_id}">${esc(t.feature_name)}</a>` : `<span class="muted">${esc(t.feature_name)}</span>`}${t.attribution === "inferred" ? ' <span class="tiny muted" title="Feature inferred from text">(inferred)</span>' : ""}</td>
      <td>${catBadge(t.category)}</td>
      <td class="r num ${t.sentiment < 0 ? "neg" : "pos"}">${t.sentiment.toFixed(2)}</td>
      <td class="small">${esc(t.cluster_name)}</td><td class="small">${esc(t.source)}</td><td class="small num">${String(t.created_at || "").slice(0, 10)}</td>
      <td class="tiny muted">${esc(t.label_source)}</td></tr>`).join("") || '<tr><td colspan="8" class="empty">No tickets match.</td></tr>';
    $("#tk-page").textContent = res.total ? `${ui.offset + 1}–${Math.min(ui.offset + LIMIT, res.total)} of ${num(res.total)}` : "";
    $("#tk-prev").disabled = ui.offset === 0;
    $("#tk-next").disabled = ui.offset + LIMIT >= res.total;
    $$("#tk-body [data-open]").forEach((a) => a.addEventListener("click", () => ctx.openFeature(a.dataset.open)));
  };
  const reset = () => { ui.offset = 0; load(); };
  $("#tk-q").addEventListener("input", debounce((e) => { ui.q = e.target.value; reset(); }, 300));
  $("#tk-cat").addEventListener("change", (e) => { ui.category = e.target.value; reset(); });
  $("#tk-feat").addEventListener("change", (e) => { ui.feature_id = e.target.value; reset(); });
  $("#tk-theme").addEventListener("change", (e) => { ui.cluster_id = e.target.value === "" ? null : Number(e.target.value); syncClusters(); reset(); });
  $("#tk-prev").addEventListener("click", () => { ui.offset = Math.max(0, ui.offset - LIMIT); load(); });
  $("#tk-next").addEventListener("click", () => { ui.offset += LIMIT; load(); });
  const syncClusters = () => $$(".cluster", root).forEach((el) => el.classList.toggle("selected", Number(el.dataset.cluster) === ui.cluster_id));
  $$(".cluster", root).forEach((el) => el.addEventListener("click", () => {
    const id = Number(el.dataset.cluster);
    ui.cluster_id = ui.cluster_id === id ? null : id;
    $("#tk-theme").value = ui.cluster_id ?? "";
    syncClusters();
    reset();
    $("#tk-q").scrollIntoView({ behavior: "smooth", block: "center" });
  }));
  load();
}

// ===========================================================================
// PORTFOLIO & SCENARIO
// ===========================================================================
const COLS = [
  ["feature_name", "Feature", (f) => featureCell(f)],
  ["complexity_index", "Complexity", (f) => `${miniBar(f.complexity_index, 100, "#f97316")}${f.complexity_index.toFixed(0)}`, "r"],
  ["roi_index", "ROI", (f) => `${miniBar(f.roi_index, 100, "#4f46e5")}${f.roi_index.toFixed(0)}`, "r"],
  ["quadrant", "Quadrant", (f) => `<span style="color:${COLORS.quadrant[f.quadrant]};font-weight:600">${esc(f.quadrant)}</span>`],
  ["bcg", "BCG", (f) => esc(f.bcg)],
  ["plc_stage", "Lifecycle", (f) => esc(f.plc_stage)],
  ["maintenance_hours", "Hrs/mo", (f) => num(f.maintenance_hours), "r"],
  ["eng_cost_monthly", "Eng cost/mo", (f) => inr(f.eng_cost_monthly), "r"],
  ["monthly_revenue_inr", "Revenue/mo", (f) => inr(f.monthly_revenue_inr), "r"],
  ["net_contribution_monthly", "Net/mo", (f) => `<span class="${f.net_contribution_monthly < 0 ? "neg" : ""}">${inr(f.net_contribution_monthly)}</span>`, "r"],
  ["adoption_rate", "Adoption", (f) => pct(f.adoption_rate, 1), "r"],
  ["usage_growth", "Growth", (f) => `<span class="${f.usage_growth < 0 ? "neg" : "pos"}">${spct(f.usage_growth)}</span>`, "r"],
  ["enterprise_clients", "Ent. clients", (f) => num(f.enterprise_clients), "r"],
  ["avg_sentiment", "Sentiment", (f) => num(f.avg_sentiment, 2), "r"],
  ["action", "Action", (f) => badge(f.action)],
  ["confidence", "Conf.", (f) => esc(f.confidence)],
];

async function portfolio(root, ctx) {
  const { features } = ctx.state.analysis;
  const ui = (ctx.state.ui.portfolio ||= { sort: "trap_score", dir: -1, q: "", action: "", quadrant: "", selected: null, retention: 0.4 });
  if (!ui.selected || ui.version !== ctx.state.version) {
    ui.selected = new Set(features.filter((f) => f.action === "Sunset").map((f) => f.feature_id));
    ui.version = ctx.state.version;
  }
  root.innerHTML = `
    <div class="scenario" id="scn"></div>
    <div class="card">
      <div class="toolbar" style="margin-bottom:12px">
        <input type="search" id="pf-q" placeholder="Search features…" value="${esc(ui.q)}" />
        <select id="pf-action"><option value="">All actions</option>${["Invest", "Retain", "Refactor", "Monitor", "Sunset"].map((a) => `<option>${a}</option>`).join("")}</select>
        <select id="pf-quad"><option value="">All quadrants</option>${Object.keys(COLORS.quadrant).map((a) => `<option>${a}</option>`).join("")}</select>
        <button class="btn" id="pf-sel-sunset">Select recommended sunsets</button>
        <button class="btn" id="pf-sel-traps">Select all traps</button>
        <button class="btn ghost" id="pf-clear">Clear selection</button>
        <a class="btn primary" style="margin-left:auto" href="/api/export/features.csv?${ctx.paramsQS()}" download>⤓ Export CSV</a>
      </div>
      <div class="table-wrap" style="max-height:640px"><table><thead><tr><th><input type="checkbox" id="pf-all" title="Select visible"/></th>
        ${COLS.map(([k, l, , cls]) => `<th class="sortable ${cls || ""}" data-sort="${k}">${l}<span class="arrow">${ui.sort === k ? (ui.dir > 0 ? "▲" : "▼") : ""}</span></th>`).join("")}
      </tr></thead><tbody id="pf-body"></tbody></table></div>
      <div class="muted small" style="margin-top:10px">Click a row for the full feature diagnosis. Tick features to add them to the sunset scenario above.</div>
    </div>`;

  const visible = () => features
    .filter((f) => (!ui.q || f.feature_name.toLowerCase().includes(ui.q.toLowerCase()) || f.module.toLowerCase().includes(ui.q.toLowerCase()))
      && (!ui.action || f.action === ui.action) && (!ui.quadrant || f.quadrant === ui.quadrant))
    .sort((a, b) => {
      const x = a[ui.sort], y = b[ui.sort];
      return (typeof x === "string" ? x.localeCompare(y) : (x ?? -1e18) - (y ?? -1e18)) * ui.dir;
    });

  const renderScenario = () => {
    const sel = features.filter((f) => ui.selected.has(f.feature_id));
    const savings = sel.reduce((a, f) => a + f.eng_cost_monthly, 0) * 12;
    const revLost = sel.reduce((a, f) => a + f.monthly_revenue_inr, 0) * 12 * (1 - ui.retention);
    const fte = sel.reduce((a, f) => a + f.maintenance_hours, 0) / 140;
    const net = savings - revLost;
    const devSunk = sel.reduce((a, f) => a + f.development_cost_inr, 0);
    $("#scn").innerHTML = `
      <div><div class="k">Features sunset</div><div class="v">${sel.length}</div></div>
      <div><div class="k">Eng cost avoided / yr</div><div class="v">${inr(savings)}</div></div>
      <div><div class="k">Revenue at risk / yr</div><div class="v">${inr(revLost)}</div></div>
      <div><div class="k">Capacity freed</div><div class="v">${fte.toFixed(1)} FTE</div></div>
      <div><div class="k">Net annual impact</div><div class="v" style="color:${net >= 0 ? "#6ee7b7" : "#fca5a5"}">${inr(net)}</div></div>
      <div><div class="k">Revenue retained after sunset · ${pct(ui.retention)}</div>
        <input type="range" id="scn-ret" min="0" max="1" step="0.05" value="${ui.retention}" />
        <div class="tiny" style="color:#a5b4fc">Customers who migrate to alternatives. Sunk dev cost ignored: ${inr(devSunk)}</div></div>`;
    $("#scn-ret").addEventListener("input", (e) => { ui.retention = Number(e.target.value); renderScenario(); });
  };

  const renderRows = () => {
    const rows = visible();
    $("#pf-body").innerHTML = rows.map((f) => `<tr class="clickable" data-fid="${f.feature_id}"><td><input type="checkbox" data-sel="${f.feature_id}" ${ui.selected.has(f.feature_id) ? "checked" : ""}/></td>
      ${COLS.map(([, , fn, cls]) => `<td class="${cls || ""} num">${fn(f)}</td>`).join("")}</tr>`).join("");
    $$("[data-sel]", root).forEach((cb) => cb.addEventListener("change", () => {
      cb.checked ? ui.selected.add(cb.dataset.sel) : ui.selected.delete(cb.dataset.sel);
      renderScenario();
    }));
    bindRowClicks($("#pf-body"), ctx);
  };

  $("#pf-action").value = ui.action;
  $("#pf-quad").value = ui.quadrant;
  $("#pf-q").addEventListener("input", debounce((e) => { ui.q = e.target.value; renderRows(); }, 200));
  $("#pf-action").addEventListener("change", (e) => { ui.action = e.target.value; renderRows(); });
  $("#pf-quad").addEventListener("change", (e) => { ui.quadrant = e.target.value; renderRows(); });
  $("#pf-sel-sunset").addEventListener("click", () => { ui.selected = new Set(features.filter((f) => f.action === "Sunset").map((f) => f.feature_id)); renderRows(); renderScenario(); });
  $("#pf-sel-traps").addEventListener("click", () => { ui.selected = new Set(features.filter((f) => f.is_complexity_trap).map((f) => f.feature_id)); renderRows(); renderScenario(); });
  $("#pf-clear").addEventListener("click", () => { ui.selected = new Set(); renderRows(); renderScenario(); });
  $("#pf-all").addEventListener("change", (e) => { visible().forEach((f) => (e.target.checked ? ui.selected.add(f.feature_id) : ui.selected.delete(f.feature_id))); renderRows(); renderScenario(); });
  $$("th[data-sort]", root).forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.sort;
    ui.dir = ui.sort === k ? -ui.dir : (typeof features[0][k] === "string" ? 1 : -1);
    ui.sort = k;
    $$("th[data-sort] .arrow", root).forEach((a) => (a.textContent = ""));
    $(".arrow", th).textContent = ui.dir > 0 ? "▲" : "▼";
    renderRows();
  }));
  renderRows();
  renderScenario();
}

// ===========================================================================
// DATA & PIPELINE
// ===========================================================================
async function data(root, ctx) {
  const s = ctx.state.status || (await api("/api/status"));
  const ds = s.dataset || {};
  const nlp = s.nlp || {};
  const cfg = s.config || {};
  const tables = [
    ["features", "features.csv", true, "feature_id, feature_name, module, tier, release_date, development_cost_inr, monthly_revenue_inr, enterprise_clients, eligible_users"],
    ["usage", "usage_monthly.csv", false, "feature_id, month, active_users"],
    ["engineering", "engineering_logs.csv", false, "feature_id, month, maintenance_hours, bug_tickets, commits, incidents"],
    ["feedback", "feedback.csv", false, "ticket_id, feature_id (optional), source, created_at, text"],
  ];
  root.innerHTML = `
    <div class="grid g2">
      ${card("Upload enterprise data", "CSV exports from your product DB, analytics, Jira/GitHub and Zendesk. Only features.csv is required.",
        `<form id="up-form" class="grid" style="gap:10px">
          ${tables.map(([k, fn, req, cols]) => `<div class="dropzone ${req ? "req" : ""}"><div style="display:flex;justify-content:space-between"><b>${fn}${req ? " *" : ""}</b><a href="/api/datasets/template/${k}" download class="small">template ⤓</a></div>
            <div class="tiny muted mono">${cols}</div><input type="file" name="${k}" accept=".csv,text/csv" ${req ? "required" : ""}/></div>`).join("")}
          <div class="tiny muted">Flat alternative: put <span class="mono">active_users</span>, <span class="mono">monthly_maintenance_hours</span> and <span class="mono">bug_tickets_per_month</span> columns directly on features.csv. Common aliases (e.g. <span class="mono">direct_revenue_attributed</span>, <span class="mono">tier_dependency</span>) are mapped automatically.</div>
          <div><button class="btn primary" type="submit">Upload &amp; run pipeline</button></div>
          <div id="up-msg"></div>
        </form>`)}
      <div class="grid" style="gap:18px">
        ${card("Synthetic enterprise dataset", "Generate a fresh, realistic SaaS portfolio (42 features, 24 months, ~1.6k tickets) with hidden archetypes the pipeline must rediscover.",
          `<div class="toolbar"><label class="small">Seed <input type="number" id="syn-seed" value="${Math.floor(Math.random() * 1000)}" style="width:100px"/></label>
            <label class="small">Feedback volume <select id="syn-scale"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="3">3×</option></select></label>
            <button class="btn primary" id="syn-go">Generate &amp; analyse</button></div>`)}
        ${card("Current dataset", "",
          `<div class="kv"><div class="k">Name</div><div>${esc(ds.name || "–")}</div>
            <div class="k">Features</div><div>${num(ds.n_features)}</div>
            <div class="k">Feedback tickets</div><div>${num(ds.n_tickets)}</div>
            <div class="k">Usage / engineering rows</div><div>${num(ds.n_usage_rows)} / ${num(ds.n_engineering_rows)}</div>
            <div class="k">Period</div><div>${esc(ds.period_start || "–")} → ${esc(ds.period_end || "–")}</div></div>
            ${(ds.warnings || []).map((w) => `<div class="warn" style="margin-top:10px">${esc(w)}</div>`).join("")}
            ${s.error ? `<div class="err" style="margin-top:10px">${esc(s.error)}</div>` : ""}`)}
      </div>
    </div>
    <div class="grid g2">
      ${card("Intelligence layer", "How feedback is being labelled",
        `<div class="kv">
          <div class="k">Active provider</div><div><b>${esc(s.llm?.provider || "–")}</b> ${s.llm?.enabled ? "· " + esc(s.llm.model) : "(offline rules + lexicon)"}</div>
          <div class="k">LLM calls / failures</div><div>${num(s.llm?.calls || 0)} / ${num(s.llm?.failures || 0)}</div>
          <div class="k">Provider setting</div><div class="mono">LLM_PROVIDER=${esc(cfg.llm_provider_setting)}</div>
          <div class="k">Ollama</div><div class="mono">${esc(cfg.ollama_host)} · ${esc(cfg.ollama_model)}</div>
          <div class="k">LLM ticket budget</div><div>${num(cfg.llm_ticket_budget)} tickets labelled directly, rest via k-NN propagation</div>
          <div class="k">Embeddings</div><div>${esc(nlp.embedding_backend || "–")} · ${esc(nlp.embedding_model || "")} · seed-lexicon weight ${nlp.theme_seed_weight ?? "–"}</div>
          <div class="k">Vector index</div><div>${esc(nlp.vector_index || "–")}</div>
        </div>
        <div class="formula" style="margin-top:14px">To enable a local LLM: <b>ollama pull llama3.1</b> then restart with LLM_PROVIDER=auto (or docker compose --profile llm up).<br>For an API model: set OPENAI_API_KEY (+ OPENAI_BASE_URL for Groq/Together/vLLM).</div>`)}
      ${card("Cluster count selection", "Silhouette score per candidate k — parsimonious k within 0.02 of the best is chosen (red)", '<div id="k-chart"></div>')}
    </div>
    ${card("Exports", "",
      `<div class="toolbar"><a class="btn" href="/api/export/features.csv?${ctx.paramsQS()}" download>⤓ Feature analysis (CSV)</a>
        <a class="btn" href="/api/export/tickets.csv" download>⤓ Mined feedback (CSV)</a>
        <a class="btn" href="/api/export/memo.md?${ctx.paramsQS()}" download>⤓ Executive memo (Markdown)</a>
        <a class="btn ghost" href="/docs" target="_blank">API docs ↗</a></div>`)}
  `;
  if (nlp.k_scores) charts.kScores($("#k-chart"), nlp.k_scores, nlp.n_clusters);

  $("#syn-go").addEventListener("click", async () => {
    try {
      await api("/api/datasets/synthetic", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seed: Number($("#syn-seed").value) || 0, feedback_scale: Number($("#syn-scale").value) }) });
      toast("Generating dataset & running pipeline…");
      ctx.startedRun();
    } catch (e) { toast(e.message); }
  });
  $("#up-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData();
    $$("#up-form input[type=file]").forEach((inp) => inp.files[0] && fd.append(inp.name, inp.files[0]));
    $("#up-msg").innerHTML = '<div class="muted small">Uploading…</div>';
    try {
      await api("/api/datasets/upload", { method: "POST", body: fd });
      $("#up-msg").innerHTML = "";
      toast("Upload accepted — running pipeline…");
      ctx.startedRun();
    } catch (err) {
      $("#up-msg").innerHTML = `<div class="err">${esc(err.message)}</div>`;
    }
  });
}

export const VIEWS = { overview, matrix, bcg, plc, feedback, portfolio, data };
