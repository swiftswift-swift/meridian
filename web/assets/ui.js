/* Small DOM helpers.

   Deliberately not a framework. These pages re-render whole sections rather than diffing, which
   is fine at this size and keeps the whole UI readable without a build step. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value === null || value === undefined ? "" : String(value);
  return div.innerHTML;
}

export function toast(message, kind = "info") {
  let stack = $("#toasts");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toasts";
    stack.className = "toast-stack";
    stack.setAttribute("role", "status");
    stack.setAttribute("aria-live", "polite");
    document.body.append(stack);
  }
  const node = document.createElement("div");
  node.className = "toast";
  node.dataset.kind = kind;
  node.textContent = message;
  stack.append(node);
  setTimeout(() => {
    node.style.opacity = "0";
    setTimeout(() => node.remove(), 220);
  }, 4600);
}

export function money(value) {
  const n = Number(value) || 0;
  if (Math.abs(n) >= 1000000) return `$${(n / 1000000).toFixed(2)}M`;
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}k`;
  return `$${n.toFixed(2)}`;
}

export function exactMoney(value) {
  return `$${Math.round(Number(value) || 0).toLocaleString()}`;
}

export function cell(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  }
  return String(value);
}

export function duration(ms) {
  const seconds = (Number(ms) || 0) / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function since(iso) {
  const then = new Date(iso);
  let value = Math.max(1, (Date.now() - then.getTime()) / 1000);
  const steps = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
  ];
  for (const [size, unit] of steps) {
    if (value < size) {
      const rounded = Math.floor(value);
      return `${rounded} ${unit}${rounded === 1 ? "" : "s"} ago`;
    }
    value /= size;
  }
  return then.toLocaleDateString();
}

export function table(columns, rows, { limit = 50 } = {}) {
  if (!rows || !rows.length) return `<p class="muted">No rows returned.</p>`;
  const head = columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const body = rows
    .slice(0, limit)
    .map(
      (row) =>
        `<tr>${columns.map((c) => `<td>${escapeHtml(cell(row[c]))}</td>`).join("")}</tr>`,
    )
    .join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

export function skeleton(lines = 3) {
  const bars = [];
  for (let i = 0; i < lines; i += 1) bars.push("<span></span>");
  return `<div class="skeleton">${bars.join("")}</div>`;
}

export function emptyState({ title, body, actionLabel, actionHref }) {
  const action = actionHref
    ? `<a class="btn btn-primary" href="${escapeHtml(actionHref)}" data-link>${escapeHtml(actionLabel)}</a>`
    : "";
  return `<div class="empty"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p>${action}</div>`;
}

export function errorState(error, retryLabel = "Try again") {
  return `
    <div class="empty error">
      <h3>That did not work</h3>
      <p>${escapeHtml(error.message || "Something failed.")}</p>
      <button class="btn btn-ghost" data-retry>${escapeHtml(retryLabel)}</button>
    </div>`;
}

export function barChart(rows, { legend = [], format = money } = {}) {
  if (!rows.length) return `<p class="muted">Nothing to chart yet.</p>`;
  const values = [];
  for (const row of rows) {
    values.push(row.a ?? 0);
    if (row.b !== undefined) values.push(row.b);
  }
  const peak = Math.max(...values) || 1;
  const bars = rows
    .map((row) => {
      const second =
        row.b === undefined
          ? ""
          : `<div class="chart-bar alt" style="width:${Math.max(1, (row.b / peak) * 100)}%"><span>${escapeHtml(row.bLabel || format(row.b))}</span></div>`;
      return `
      <div class="chart-row">
        <span>${escapeHtml(row.label)}</span>
        <div class="chart-bars">
          <div class="chart-bar" style="width:${Math.max(1, (row.a / peak) * 100)}%"><span>${escapeHtml(row.aLabel || format(row.a))}</span></div>
          ${second}
        </div>
      </div>`;
    })
    .join("");
  const key = legend.length
    ? `<div class="chart-legend">${legend
        .map(
          (label, index) =>
            `<span><i style="background:var(--${index === 0 ? "accent" : "accent-dim"})"></i>${escapeHtml(label)}</span></span>`,
        )
        .join("")}</div>`
    : "";
  return `<div class="chart">${bars}${key}</div>`;
}

export function sparkline(values, { width = 240, height = 44 } = {}) {
  if (!values.length) return "";
  const peak = Math.max(...values, 1);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values
    .map((value, index) => `${(index * step).toFixed(1)},${(height - (value / peak) * height).toFixed(1)}`)
    .join(" ");
  return `
    <svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="trend">
      <polyline points="${points}" fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke" />
    </svg>`;
}

export function scoreBadge(score) {
  const percent = Math.round((Number(score) || 0) * 100);
  const kind = percent >= 80 ? "good" : percent >= 50 ? "warn" : "bad";
  return `<span class="badge badge-${kind}">${percent}% verified</span>`;
}

export function statusBadge(status) {
  const kind = status === "completed" ? "good" : status === "failed" ? "bad" : "warn";
  return `<span class="badge badge-${kind}">${escapeHtml(status)}</span>`;
}
