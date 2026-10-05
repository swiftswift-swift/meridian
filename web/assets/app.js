/* Meridian interface behaviour.
 *
 * No framework and no build step on purpose: the React and Vite phase is not built yet, and a
 * half-finished bundler setup would be worse than none. Everything here talks to the real API.
 */

(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const state = {
    token: sessionStorage.getItem("meridian.token") || null,
    user: null,
  };

  /* ---------------------------------------------------------------- api ---- */

  async function api(path, { method = "GET", body } = {}) {
    const headers = { Accept: "application/json" };
    if (body) headers["Content-Type"] = "application/json";
    if (state.token) headers.Authorization = `Bearer ${state.token}`;

    const response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;
    if (!response.ok) {
      // Every error from this API is an RFC 9457 problem document, so there is one shape to read.
      const detail = payload?.detail || `Request failed with status ${response.status}`;
      throw Object.assign(new Error(detail), { status: response.status, problem: payload });
    }
    return payload;
  }

  /* -------------------------------------------------------------- toasts ---- */

  function toast(message, kind = "info") {
    const node = document.createElement("div");
    node.className = "toast";
    node.dataset.kind = kind;
    node.textContent = message;
    $("#toasts").append(node);
    setTimeout(() => {
      node.style.opacity = "0";
      setTimeout(() => node.remove(), 220);
    }, 4200);
  }

  /* --------------------------------------------------------------- theme ---- */

  function initTheme() {
    const stored = localStorage.getItem("meridian.theme");
    const prefersLight = window.matchMedia("(prefers-color-scheme: light)").matches;
    applyTheme(stored || (prefersLight ? "light" : "dark"));
    $("#theme-toggle").addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
      localStorage.setItem("meridian.theme", next);
    });
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    $("[data-theme-icon]").textContent = theme === "dark" ? "Light" : "Dark";
  }

  /* ---------------------------------------------------- the hero run replay ---- */

  // A replay of the scripted run, with the figures the seeded data actually produces. The source
  // panel content is the real SQL and the real rows, so clicking a citation shows what the agent
  // would have seen.
  const PLAN = [
    "Compare EMEA revenue by quarter in both USD and local currency",
    "Measure the EUR/USD move between the two quarters",
    "Identify accounts that churned at the end of Q2",
    "Search internal documents for an explanation",
    "Attribute the decline between currency and account loss",
  ];

  const TIMELINE = [
    {
      tool: "sql_query",
      arg: "SELECT quarter, SUM(subtotal_usd) AS usd, SUM(subtotal_local) AS local\nFROM orders ... WHERE regions.code = 'EMEA'\nGROUP BY quarter",
      note: "Reported USD fell 5.7% while local currency rose 2.2%. The decline is not volume.",
      meta: "214 ms · 4 rows",
      step: 0,
    },
    {
      tool: "exchange_rates",
      arg: '{ "base": "EUR", "quote": "USD", "from": "2025-04-01", "to": "2025-09-30" }',
      note: "EUR/USD moved 1.092 to 0.995, a fall of 8.9%.",
      meta: "341 ms · frankfurter",
      step: 1,
    },
    {
      tool: "sql_query",
      arg: "SELECT name, churned_on, annual_contract_usd\nFROM customers WHERE churned_on IS NOT NULL",
      note: "Helvetica Logistics churned 2025-06-30; it was 9.5% of EMEA Q2 revenue.",
      meta: "38 ms · 1 row",
      step: 2,
    },
    {
      tool: "knowledge_search",
      arg: '{ "query": "EMEA Q3 revenue decline currency account loss", "limit": 5 }',
      note: "Two documents attribute the decline to currency plus the known non-renewal.",
      meta: "77 ms · 5 passages",
      step: 3,
    },
    {
      tool: "calculator",
      arg: '{ "expression": "(8926124 - 9468359) / 9468359 * 100" }',
      note: "-5.73%. Local-currency change is +2.2%, so currency accounts for 7.9 points.",
      meta: "2 ms",
      step: 4,
    },
  ];

  const SOURCES = {
    S1: {
      title: "S1 — sql_query (read-only)",
      body: `SELECT substr(o.order_date,1,4)||'Q'||((CAST(substr(o.order_date,6,2) AS INT)-1)/3+1) AS quarter,
       ROUND(SUM(o.subtotal_usd))   AS usd,
       ROUND(SUM(o.subtotal_local)) AS local
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN countries k ON k.id = c.country_id
JOIN regions   r ON r.id = k.region_id
WHERE r.code = 'EMEA' AND o.status = 'fulfilled'
  AND o.order_date >= '2025-01-01'
GROUP BY quarter
LIMIT 500

quarter   usd          local
------- ------------ ------------
2025Q1     8,627,338    7,778,758
2025Q2     9,468,359    8,471,109
2025Q3     8,926,124    8,657,151
2025Q4     9,881,859    9,448,881`,
    },
    S2: {
      title: "S2 — exchange_rates (Frankfurter)",
      body: `GET https://api.frankfurter.app/2025-04-01..2025-09-30?from=EUR&to=USD

quarter   average EUR/USD
------- -----------------
2025Q2             1.0920
2025Q3             0.9950

change: -8.9%`,
    },
    S3: {
      title: "S3 — sql_query (read-only)",
      body: `SELECT name, churned_on, annual_contract_usd
FROM customers
WHERE churned_on IS NOT NULL
LIMIT 500

name                   churned_on    annual_contract_usd
--------------------- ------------ ---------------------
Helvetica Logistics    2025-06-30              820,000.0

share of EMEA Q2 2025 revenue: 9.5%`,
    },
    S4: {
      title: "S4 — knowledge_search (internal documents)",
      body: `document: FY2025 Q3 EMEA Business Review
chunk 1 of 3 · characters 142-889 · trust: internal

"Reported EMEA revenue in USD declined quarter on quarter. The regional
 leadership team's assessment is that the decline is largely a reporting-
 currency effect rather than a demand problem, compounded by one account
 loss that was known and forecast."

"Helvetica Logistics did not renew at the end of Q2. The account was our
 second largest in the region. The non-renewal was not a competitive loss:
 the customer was acquired and the acquirer had an incumbent platform."`,
    },
  };

  const CHART = [
    { label: "2025Q1", usd: 8627338, local: 7778758 },
    { label: "2025Q2", usd: 9468359, local: 8471109 },
    { label: "2025Q3", usd: 8926124, local: 8657151 },
    { label: "2025Q4", usd: 9881859, local: 9448881 },
  ];

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let runToken = 0;

  async function playRun() {
    const mine = ++runToken;
    const planList = $("#plan-list");
    const timeline = $("#timeline");
    const report = $("#report");
    const alive = () => mine === runToken;

    planList.innerHTML = "";
    timeline.innerHTML = "";
    report.hidden = true;
    $("#source-panel").hidden = true;

    // 1. The plan appears first, one step at a time.
    for (const [index, text] of PLAN.entries()) {
      if (!alive()) return;
      const li = document.createElement("li");
      li.dataset.state = "pending";
      li.dataset.index = String(index);
      li.innerHTML = `<span class="tick">[ ]</span><span>${text}</span>`;
      planList.append(li);
      await sleep(240);
    }

    // 2. The approval interrupt. The graph genuinely stops here and waits.
    if (!alive()) return;
    const approval = document.createElement("div");
    approval.className = "approval";
    approval.innerHTML = `
      <h4>Approve this plan before the run spends anything</h4>
      <p class="muted" style="margin:0;font-size:13px">
        Five steps, budget: 8 steps / 90,000 tokens / $0.25 / 240 s.
      </p>
      <div class="approval-actions">
        <button class="btn btn-primary btn-sm" data-approve>Approve and run</button>
        <button class="btn btn-ghost btn-sm" data-edit>Edit steps</button>
      </div>`;
    timeline.append(approval);

    await new Promise((resolve) => {
      $("[data-approve]", approval).addEventListener("click", resolve, { once: true });
      $("[data-edit]", approval).addEventListener(
        "click",
        () => {
          toast("Editing the plan is part of the run page, which is not built yet.", "info");
        },
        { once: false },
      );
      // Auto-approve so an unattended page still completes the demo.
      setTimeout(resolve, 5200);
    });
    if (!alive()) return;
    approval.remove();

    // 3. Each step runs, its tool card streams in, and the plan ticks over.
    for (const entry of TIMELINE) {
      if (!alive()) return;
      const li = $(`#plan-list li[data-index="${entry.step}"]`);
      if (li) {
        li.dataset.state = "running";
        $(".tick", li).textContent = "[~]";
      }

      const card = document.createElement("div");
      card.className = "tool-card";
      card.dataset.state = "running";
      card.innerHTML = `
        <div class="tool-head">
          <span class="spinner"></span>
          <span class="tool-name">${entry.tool}</span>
          <span class="tool-meta">running</span>
        </div>
        <div class="tool-arg">${escapeHtml(entry.arg)}</div>`;
      timeline.append(card);
      card.scrollIntoView({ block: "nearest", behavior: "smooth" });

      await sleep(820);
      if (!alive()) return;

      card.dataset.state = "done";
      $(".spinner", card).replaceWith(Object.assign(document.createElement("span"), {
        className: "tick",
        textContent: "✓",
        style: "color:var(--good);font-family:var(--mono);font-size:12px",
      }));
      $(".tool-meta", card).textContent = entry.meta;
      const note = document.createElement("div");
      note.className = "tool-note";
      note.textContent = entry.note;
      card.append(note);

      if (li) {
        li.dataset.state = "done";
        $(".tick", li).textContent = "[x]";
      }
      await sleep(260);
    }

    // 4. The report, with its chart drawn from the cited rows.
    if (!alive()) return;
    await sleep(380);
    renderChart();
    report.hidden = false;
    report.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function renderChart() {
    const chart = $("#chart");
    const peak = Math.max(...CHART.flatMap((row) => [row.usd, row.local]));
    const money = (value) => `$${(value / 1_000_000).toFixed(2)}M`;
    chart.innerHTML =
      CHART.map(
        (row) => `
        <div class="chart-row">
          <span>${row.label}</span>
          <div class="chart-bars">
            <div class="chart-bar" style="width:${(row.usd / peak) * 100}%"><span>${money(row.usd)}</span></div>
            <div class="chart-bar alt" style="width:${(row.local / peak) * 100}%"><span>${money(row.local)}</span></div>
          </div>
        </div>`,
      ).join("") +
      `<div class="chart-legend">
         <span><i style="background:var(--accent)"></i>USD reported</span>
         <span><i style="background:var(--accent-dim)"></i>Local currency</span>
       </div>`;
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  function initCitations() {
    document.addEventListener("click", (event) => {
      const chip = event.target.closest("cite[data-src]");
      if (!chip) return;
      const source = SOURCES[chip.dataset.src];
      if (!source) return;
      $("#source-title").textContent = source.title;
      $("#source-body").textContent = source.body;
      const panel = $("#source-panel");
      panel.hidden = false;
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    $("#close-source").addEventListener("click", () => {
      $("#source-panel").hidden = true;
    });
  }

  /* ----------------------------------------------------------- auth / demo ---- */

  async function signInDemo(role = "analyst") {
    try {
      const session = await api("/auth/demo", { method: "POST", body: { role } });
      state.token = session.access_token;
      state.user = session.user;
      sessionStorage.setItem("meridian.token", session.access_token);
      toast(`Signed in as ${session.user.display_name} (${session.user.role})`, "success");
      onSignedIn();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function onSignedIn() {
    const label = state.user ? `${state.user.display_name} · ${state.user.role}` : "Signed in";
    for (const id of ["#try-demo", "#hero-demo"]) {
      const button = $(id);
      if (button) {
        button.textContent = label;
        button.disabled = true;
      }
    }
    $("#pg-hint").textContent = "Queries run against the read-only company database";
    $("#run-sql").disabled = false;
    loadProviders();
    loadLiveStats();
  }

  async function restoreSession() {
    if (!state.token) {
      $("#run-sql").disabled = true;
      return;
    }
    try {
      state.user = await api("/auth/me");
      onSignedIn();
    } catch {
      // An expired token is not an error worth showing; it just means signing in again.
      state.token = null;
      sessionStorage.removeItem("meridian.token");
      $("#run-sql").disabled = true;
    }
  }

  /* ------------------------------------------------------------ playground ---- */

  const PRESETS = [
    {
      label: "EMEA by quarter",
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
      label: "Growth vs margin",
      kind: "ok",
      sql: `SELECT pl.name, pl.gross_margin_pct,
       ROUND(SUM(CASE WHEN o.order_date < '2025-01-01' THEN oi.line_total_usd ELSE 0 END)) AS y2024,
       ROUND(SUM(CASE WHEN o.order_date >= '2025-01-01' THEN oi.line_total_usd ELSE 0 END)) AS y2025
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
JOIN product_lines pl ON pl.id = p.product_line_id
WHERE o.status = 'fulfilled'
GROUP BY pl.name`,
    },
    {
      label: "Campaign ROI",
      kind: "ok",
      sql: `SELECT campaign, ROUND(SUM(spend_usd)) AS spend,
       ROUND(SUM(attributed_revenue_usd) / SUM(spend_usd), 2) AS roi
FROM marketing_spend
GROUP BY campaign`,
    },
    { label: "DROP TABLE orders", kind: "attack", sql: "DROP TABLE orders" },
    { label: "DELETE FROM orders", kind: "attack", sql: "DELETE FROM orders" },
    { label: "UPDATE orders SET ...", kind: "attack", sql: "UPDATE orders SET subtotal_usd = 0" },
    { label: "Chained statement", kind: "attack", sql: "SELECT 1; DROP TABLE orders" },
    { label: "Read the users table", kind: "attack", sql: "SELECT * FROM users" },
    { label: "load_extension()", kind: "attack", sql: "SELECT load_extension('evil.dll')" },
    { label: "PRAGMA probe", kind: "attack", sql: "PRAGMA table_info(orders)" },
    {
      label: "CTE named delete_me",
      kind: "ok",
      sql: "WITH delete_me AS (SELECT id FROM orders) SELECT COUNT(*) FROM delete_me",
    },
  ];

  function initPlayground() {
    const presets = $("#pg-presets");
    for (const preset of PRESETS) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pg-preset";
      button.dataset.kind = preset.kind;
      button.textContent = preset.label;
      button.addEventListener("click", () => {
        $("#sql-input").value = preset.sql;
        runSql();
      });
      presets.append(button);
    }
    $("#run-sql").addEventListener("click", runSql);
    $("#sql-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) runSql();
    });
  }

  async function runSql() {
    const sql = $("#sql-input").value.trim();
    const panel = $("#pg-result");
    if (!sql) return;
    if (!state.token) {
      toast("Sign in with the demo account first.", "error");
      return;
    }

    panel.innerHTML = '<p class="muted">Running…</p>';
    try {
      const result = await api("/datasources/sql-check", { method: "POST", body: { sql } });
      panel.innerHTML = result.refused || !result.ok ? renderRefusal(result) : renderRows(result);
    } catch (error) {
      panel.innerHTML = `<div class="refusal"><h4>Request failed</h4><p class="muted">${escapeHtml(error.message)}</p></div>`;
    }
  }

  function renderRefusal(result) {
    const heading = result.refused ? "Refused by the SQL guard" : "The query did not run";
    const guardrail = result.guardrail
      ? `<div class="pg-meta"><span>guardrail: ${escapeHtml(result.guardrail)}</span></div>`
      : "";
    return `
      <div class="refusal">
        <h4>${heading}</h4>
        ${guardrail}
        <p class="muted">${escapeHtml(result.reason)}</p>
      </div>`;
  }

  function renderRows(result) {
    if (!result.rows.length) {
      return `<div class="pg-meta"><span>0 rows</span><span>${result.latency_ms} ms</span></div>
              <p class="muted">The query was allowed and returned no rows.</p>`;
    }
    const head = result.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
    const body = result.rows
      .slice(0, 50)
      .map(
        (row) =>
          `<tr>${result.columns.map((c) => `<td>${escapeHtml(formatCell(row[c]))}</td>`).join("")}</tr>`,
      )
      .join("");
    return `
      <div class="pg-meta">
        <span>${result.row_count} rows</span>
        <span>${result.latency_ms} ms</span>
        <span>limit ${result.limit_applied ?? "-"}</span>
        <span>tables: ${result.referenced_tables.join(", ") || "-"}</span>
      </div>
      <div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function formatCell(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
    return String(value);
  }

  /* ---------------------------------------------------------- status panel ---- */

  const STATUS = [
    ["Settings, fail-fast validation", true],
    ["Error taxonomy, problem+json", true],
    ["Port protocols", true],
    ["Read-only SQL guard", true],
    ["Budgets and stop decisions", true],
    ["Citation verification", true],
    ["Auth, JWT, RBAC", true],
    ["14-table schema", true],
    ["Seeded company data", true],
    ["Document ingest, injection screening", true],
    ["95 offline tests", true],
    ["LangGraph agent", false],
    ["Worker, queue, resume", false],
    ["SSE live run page", false],
    ["Evaluation suite", false],
    ["Docker and CI", false],
  ];

  function initStatus() {
    $("#status-grid").innerHTML = STATUS.map(
      ([label, done]) => `
        <div class="status-item" data-done="${done}">
          <span class="mark">${done ? "✓" : "○"}</span>
          <span>${label}</span>
        </div>`,
    ).join("");
  }

  async function loadProviders() {
    try {
      const providers = await api("/datasources/providers");
      const rows = [
        `model: ${providers.model}`,
        `embeddings: ${providers.embedding_provider}`,
        `tools: ${providers.tools_mode}`,
        `queue: ${providers.queue}`,
        `cache: ${providers.cache}`,
        providers.fully_offline ? "fully offline" : "network enabled",
      ];
      $("#provider-list").innerHTML = rows.map((r) => `<li>${escapeHtml(r)}</li>`).join("");
      $("#providers").hidden = false;
    } catch {
      // The status panel is decoration; failing to load it must not break the page.
    }
  }

  async function loadLiveStats() {
    try {
      const schema = await api("/datasources/schema");
      const orders = schema.find((table) => table.name === "orders");
      if (orders) {
        $('[data-stat="orders"]').textContent = orders.row_count.toLocaleString();
      }
    } catch {
      // Keep the figure already rendered in the markup.
    }
  }

  /* ----------------------------------------------------------------- boot ---- */

  function boot() {
    initTheme();
    initStatus();
    initCitations();
    initPlayground();
    $("#try-demo").addEventListener("click", () => signInDemo("admin"));
    $("#hero-demo").addEventListener("click", () => signInDemo("analyst"));
    $("#replay-run").addEventListener("click", playRun);
    restoreSession();
    playRun();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
