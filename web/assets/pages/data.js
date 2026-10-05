/* Data sources: schema browser, the knowledge base, and the live SQL guard playground. */

import { data } from "../api.js";
import { pageHeader } from "../shell.js";
import { $, errorState, escapeHtml, skeleton, table, toast } from "../ui.js";

const PRESETS = [
  {
    group: "Normal business questions",
    label: "European sales by quarter",
    kind: "ok",
    sql: `SELECT substr(o.order_date,1,4)||'Q'||((CAST(substr(o.order_date,6,2) AS INT)-1)/3+1) AS quarter,
       ROUND(SUM(o.subtotal_usd)) AS usd, ROUND(SUM(o.subtotal_local)) AS local
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN countries k ON k.id = c.country_id
JOIN regions   r ON r.id = k.region_id
WHERE r.code = 'EMEA' AND o.status = 'fulfilled' AND o.order_date >= '2025-01-01'
GROUP BY quarter`,
  },
  {
    group: "Normal business questions",
    label: "Which products grow but earn least",
    kind: "ok",
    sql: `SELECT pl.name, pl.gross_margin_pct,
       ROUND(SUM(CASE WHEN o.order_date >= '2025-01-01' THEN oi.line_total_usd ELSE 0 END)) AS y2025
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
JOIN product_lines pl ON pl.id = p.product_line_id
WHERE o.status = 'fulfilled'
GROUP BY pl.name, pl.gross_margin_pct`,
  },
  {
    group: "Normal business questions",
    label: 'A safe query containing the word "delete"',
    kind: "ok",
    sql: "WITH delete_me AS (SELECT id FROM orders) SELECT COUNT(*) AS n FROM delete_me",
  },
  { group: "Attempts to do damage", label: "Destroy the orders table", kind: "attack", sql: "DROP TABLE orders" },
  { group: "Attempts to do damage", label: "Delete every order", kind: "attack", sql: "DELETE FROM orders" },
  { group: "Attempts to do damage", label: "Set all revenue to zero", kind: "attack", sql: "UPDATE orders SET subtotal_usd = 0" },
  { group: "Attempts to do damage", label: "Sneak a second command in", kind: "attack", sql: "SELECT 1; DROP TABLE orders" },
  { group: "Attempts to do damage", label: "Read the user accounts table", kind: "attack", sql: "SELECT * FROM users" },
  { group: "Attempts to do damage", label: "Load code from a file", kind: "attack", sql: "SELECT load_extension('evil.dll')" },
  { group: "Attempts to do damage", label: "Probe database internals", kind: "attack", sql: "PRAGMA table_info(orders)" },
];

export async function dataPage(view) {
  view.innerHTML = `
    ${pageHeader({
      title: "Data sources",
      lede: "What the assistant can read, and proof of what it cannot do to it.",
    })}
    <div class="tabs" role="tablist">
      <button class="tab active" data-tab="schema" role="tab">Database</button>
      <button class="tab" data-tab="documents" role="tab">Documents</button>
      <button class="tab" data-tab="guard" role="tab">Guard playground</button>
      <button class="tab" data-tab="health" role="tab">Tool health</button>
    </div>
    <div id="tab-body">${skeleton(5)}</div>`;

  const tabs = {
    schema: renderSchema,
    documents: renderDocuments,
    guard: renderGuard,
    health: renderHealth,
  };

  view.querySelector(".tabs").addEventListener("click", (event) => {
    const button = event.target.closest(".tab");
    if (!button) return;
    view.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === button));
    tabs[button.dataset.tab]($("#tab-body"));
  });

  await renderSchema($("#tab-body"));
}

async function renderSchema(host) {
  host.innerHTML = skeleton(5);
  let tables;
  try {
    tables = await data.schema();
  } catch (error) {
    host.innerHTML = errorState(error);
    return;
  }
  const total = tables.reduce((sum, t) => sum + t.row_count, 0);
  host.innerHTML = `
    <section class="panel">
      <h3 class="panel-title">Northwind Analytics</h3>
      <p class="field-hint">
        ${tables.length} tables, ${total.toLocaleString()} rows. This database is opened read-only;
        the application's own data lives elsewhere and the assistant cannot reach it.
      </p>
      <div class="schema-grid">
        ${tables
          .map(
            (t) => `
          <article class="schema-card" data-table="${escapeHtml(t.name)}">
            <header>
              <strong>${escapeHtml(t.name)}</strong>
              <span>${t.row_count.toLocaleString()} rows</span>
            </header>
            <p>${escapeHtml(t.description)}</p>
            <div class="columns">${t.columns.map((c) => `<code>${escapeHtml(c)}</code>`).join("")}</div>
            <button class="btn btn-ghost btn-sm" data-sample="${escapeHtml(t.name)}">Sample rows</button>
            <div class="sample" hidden></div>
          </article>`,
          )
          .join("")}
      </div>
    </section>`;

  host.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-sample]");
    if (!button) return;
    const card = button.closest(".schema-card");
    const target = card.querySelector(".sample");
    if (!target.hidden) {
      target.hidden = true;
      button.textContent = "Sample rows";
      return;
    }
    target.hidden = false;
    target.innerHTML = skeleton(2);
    button.textContent = "Hide rows";
    try {
      const result = await data.sample(button.dataset.sample);
      target.innerHTML = result.ok
        ? table(result.columns, result.rows, { limit: 5 })
        : `<p class="refusal-text">${escapeHtml(result.reason)}</p>`;
    } catch (error) {
      target.innerHTML = `<p class="refusal-text">${escapeHtml(error.message)}</p>`;
    }
  });
}

async function renderDocuments(host) {
  host.innerHTML = skeleton(4);
  let documents;
  try {
    documents = await data.documents();
  } catch (error) {
    host.innerHTML = errorState(error);
    return;
  }
  const flagged = documents.filter((d) => d.is_suspicious).length;
  host.innerHTML = `
    <section class="panel">
      <h3 class="panel-title">Knowledge base</h3>
      <p class="field-hint">
        ${documents.length} documents, ${documents.reduce((s, d) => s + d.chunk_count, 0)} searchable
        passages. ${flagged} flagged as containing text addressed to the assistant.
      </p>
      <div class="doc-list">
        ${documents
          .map(
            (doc) => `
          <article class="doc-card${doc.is_suspicious ? " suspicious" : ""}">
            <header>
              <strong>${escapeHtml(doc.title)}</strong>
              <span class="doc-type">${escapeHtml(doc.doc_type)}</span>
              ${doc.is_suspicious ? '<span class="badge badge-bad">injection detected</span>' : ""}
            </header>
            ${doc.is_suspicious ? `<p class="warn-text">${escapeHtml(doc.suspicion_reason)}</p>` : ""}
            <p class="doc-excerpt">${escapeHtml(doc.excerpt)}…</p>
            <footer>${doc.chunk_count} passage${doc.chunk_count === 1 ? "" : "s"}</footer>
          </article>`,
          )
          .join("")}
      </div>
    </section>`;
}

async function renderGuard(host) {
  const groups = [];
  let current = null;
  for (const preset of PRESETS) {
    if (preset.group !== current) {
      current = preset.group;
      groups.push(`<p class="pg-group-label">${escapeHtml(current)}</p>`);
    }
    groups.push(
      `<button class="pg-preset" data-kind="${preset.kind}" type="button" data-sql="${escapeHtml(preset.sql)}">${escapeHtml(preset.label)}</button>`,
    );
  }

  host.innerHTML = `
    <section class="panel">
      <h3 class="panel-title">Guard playground</h3>
      <p class="field-hint">
        This runs the real guard against the real read-only database. Try to make it do damage.
      </p>
      <div class="playground">
        <div>
          <div class="pg-presets">${groups.join("")}</div>
          <label class="sr-only" for="sql">SQL</label>
          <textarea id="sql" rows="6" spellcheck="false">SELECT code, name FROM regions</textarea>
          <div class="pg-actions"><button class="btn btn-primary" id="run-sql">Run it</button></div>
        </div>
        <div class="pg-result" id="pg-result"><p class="muted">Results appear here.</p></div>
      </div>
    </section>`;

  host.querySelector(".pg-presets").addEventListener("click", (event) => {
    const button = event.target.closest("[data-sql]");
    if (!button) return;
    $("#sql").value = button.dataset.sql;
    run();
  });
  $("#run-sql").addEventListener("click", run);
  $("#sql").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) run();
  });

  async function run() {
    const sql = $("#sql").value.trim();
    if (!sql) return;
    const panel = $("#pg-result");
    panel.innerHTML = '<p class="muted">Running…</p>';
    try {
      const result = await data.sqlCheck(sql);
      panel.innerHTML =
        result.refused || !result.ok
          ? `<div class="refusal">
               <h4>${result.refused ? "Refused by the SQL guard" : "The query did not run"}</h4>
               ${result.guardrail ? `<div class="pg-meta"><span>guardrail: ${escapeHtml(result.guardrail)}</span></div>` : ""}
               <p class="muted">${escapeHtml(result.reason)}</p>
             </div>`
          : `<div class="pg-meta">
               <span>${result.row_count} rows</span>
               <span>${result.latency_ms} ms</span>
               <span>row cap ${result.limit_applied ?? "-"}</span>
               <span>tables: ${escapeHtml(result.referenced_tables.join(", ") || "-")}</span>
             </div>${table(result.columns, result.rows)}`;
    } catch (error) {
      panel.innerHTML = `<div class="refusal"><h4>Request failed</h4><p class="muted">${escapeHtml(error.message)}</p></div>`;
      toast(error.message, "error");
    }
  }
}

async function renderHealth(host) {
  host.innerHTML = skeleton(3);
  let providers;
  try {
    providers = await data.providers();
  } catch (error) {
    host.innerHTML = errorState(error);
    return;
  }
  const rows = [
    ["Language model", providers.model, providers.scripted ? "built-in, deterministic" : "live provider"],
    ["Embeddings", providers.embedding_provider, providers.embeddings_offline ? "offline, no download" : "remote"],
    ["External tools", providers.tools_mode, providers.tools_live ? "live network calls" : "recorded fixtures"],
    ["Queue", providers.queue, providers.queue === "redis" ? "shared" : "single process"],
    ["Cache", providers.cache, providers.cache === "redis" ? "shared" : "single process"],
  ];
  host.innerHTML = `
    <section class="panel">
      <h3 class="panel-title">Tool health</h3>
      <p class="field-hint">What this deployment is actually wired to, read from the running process.</p>
      <table class="health-table">
        <thead><tr><th>Component</th><th>Configured</th><th>Mode</th></tr></thead>
        <tbody>
          ${rows.map(([a, b, c]) => `<tr><td>${escapeHtml(a)}</td><td><code>${escapeHtml(b)}</code></td><td class="muted">${escapeHtml(c)}</td></tr>`).join("")}
        </tbody>
      </table>
      <p class="field-hint">
        ${providers.fully_offline
          ? "This process makes no outbound network calls at all."
          : "This process can make outbound calls to the configured model provider."}
      </p>
    </section>`;
}
