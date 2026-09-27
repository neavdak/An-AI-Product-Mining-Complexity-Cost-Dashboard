// Shared UI helpers: formatting, colours, API, markdown, drawers, toasts.

export const COLORS = {
  action: { Invest: "#2563eb", Retain: "#059669", Refactor: "#d97706", Monitor: "#94a3b8", Sunset: "#dc2626" },
  quadrant: {
    "Complexity Trap": "#dc2626",
    "Strategic Heavyweight": "#d97706",
    "Efficient Core": "#059669",
    "Low-Cost Long Tail": "#94a3b8",
  },
  bcg: { Star: "#2563eb", "Cash Cow": "#059669", "Question Mark": "#d97706", Dog: "#dc2626" },
  plc: { Introduction: "#8b5cf6", Growth: "#2563eb", Maturity: "#059669", Decline: "#dc2626" },
  category: {
    "Core Utility": "#10b981",
    "UX Friction": "#f59e0b",
    "Performance Issue": "#ef4444",
    "Feature Bloat Indicator": "#8b5cf6",
  },
};
export const MODULE_PALETTE = ["#4f46e5", "#0891b2", "#059669", "#d97706", "#db2777", "#7c3aed", "#0f766e", "#b45309", "#475569"];

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Indian notation: ₹1.25Cr, ₹34.5L, ₹12.3K */
export function inr(x, digits = 1) {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  const sign = x < 0 ? "-" : "";
  const a = Math.abs(x);
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(digits)}L`;
  if (a >= 1e3) return `${sign}₹${(a / 1e3).toFixed(digits)}K`;
  return `${sign}₹${a.toFixed(0)}`;
}
export const pct = (x, d = 0) => (x === null || x === undefined ? "–" : `${(x * 100).toFixed(d)}%`);
export const spct = (x, d = 0) => (x === null || x === undefined ? "–" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`);
export const num = (x, d = 0) =>
  x === null || x === undefined ? "–" : Number(x).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });

export const badge = (text, cls) => `<span class="badge ${cls || "b-" + String(text).replace(/\s+/g, "-")}">${esc(text)}</span>`;
export const catBadge = (c) => `<span class="badge cat-${String(c).replace(/\s+/g, "-")}">${esc(c)}</span>`;

export function miniBar(value, max = 100, color = "#4f46e5") {
  const w = Math.max(0, Math.min(100, (value / max) * 100));
  return `<span class="bar-mini"><span style="width:${w}%;background:${color}"></span></span>`;
}

// ---------------------------------------------------------------- API
export async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (_) { /* ignore */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

export function qs(obj) {
  const p = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && p.append(k, v));
  return p.toString();
}

// ---------------------------------------------------------------- markdown (tiny, safe)
export function markdown(md) {
  const inline = (s) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<em>$2</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  const out = [];
  let list = false;
  for (const raw of String(md || "").split("\n")) {
    const line = raw.trimEnd();
    const h = line.match(/^#{1,4}\s+(.*)/);
    const li = line.match(/^\s*[-*•]\s+(.*)/) || line.match(/^\s*\d+\.\s+(.*)/);
    if (li) {
      if (!list) { out.push("<ul>"); list = true; }
      out.push(`<li>${inline(li[1])}</li>`);
      continue;
    }
    if (list) { out.push("</ul>"); list = false; }
    if (h) out.push(`<h2>${inline(h[1])}</h2>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push("</ul>");
  return out.join("");
}

// ---------------------------------------------------------------- drawers / toast
export function openDrawer(id) {
  $(`#${id}-drawer`).classList.add("open");
  $(`#${id}-backdrop`).classList.add("open");
}
export function closeDrawer(id) {
  $(`#${id}-drawer`).classList.remove("open");
  $(`#${id}-backdrop`).classList.remove("open");
}

let toastTimer;
export function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
