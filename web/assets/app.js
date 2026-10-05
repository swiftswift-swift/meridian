/* Meridian interface behaviour.
 *
 * No framework and no build step on purpose: the React and Vite phase is not built yet, and a
 * half-configured bundler would be worse than none. Everything here talks to the real API.
 */

(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const state = {
    token: sessionStorage.getItem("meridian.token") || null,
    user: null,
    sources: {},
    runToken: 0,
  };

  const TASKS = window.MERIDIAN_TASKS;

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
      throw Object.assign(new Error(detail), { status: response.status });
    }
    return payload;
  }

  const runSqlOnServer = (sql) =>
    api("/datasources/sql-check", { method: "POST", body: { sql } });

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
    }, 4600);
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
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

  /* ------------------------------------------------------- the run window ---- */

  function revealStage() {
    const stage = $(".hero-demo");
    if (stage) stage.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function resetStage(question) {
    $("#plan-list").innerHTML = "";
    $("#timeline").innerHTML = "";
    $("#report").hidden = true;
    $("#source-panel").hidden = true;
    state.sources = {};
    if (question) {
      $(".window-title").textContent = `"${question}"`;
    }
  }

  async function renderPlan(steps, alive) {
    const list = $("#plan-list");
    for (const [index, text] of steps.entries()) {
      if (!alive()) return;
      const li = document.createElement("li");
      li.dataset.state = "pending";
      li.dataset.index = String(index);
      li.innerHTML = `<span class="tick">[ ]</span><span>${escapeHtml(text)}</span>`;
      list.append(li);
      await sleep(220);
    }
  }

  async function awaitApproval(steps, alive) {
    const card = document.createElement("div");
    card.className = "approval";
    card.innerHTML = `
      <h4>Approve this plan before anything runs</h4>
      <p class="muted" style="margin:0;font-size:13px">
        ${steps.length} steps. Nothing has been queried yet. Limit: 8 steps, $0.25, 240 seconds.
      </p>
      <div class="approval-actions">
        <button class="btn btn-primary btn-sm" data-approve>Approve and run</button>
        <button class="btn btn-ghost btn-sm" data-cancel>Cancel</button>
      </div>`;
    $("#timeline").append(card);
    card.scrollIntoView({ block: "nearest", behavior: "smooth" });

    const approved = await new Promise((resolve) => {
      $("[data-approve]", card).addEventListener("click", () => resolve(true), { once: true });
      $("[data-cancel]", card).addEventListener("click", () => resolve(false), { once: true });
      // Auto-approve so an unattended page still completes the demonstration.
      setTimeout(() => resolve(true), 6000);
    });
    if (!alive()) return false;
    card.remove();
    if (!approved) {
      addNotice("Run cancelled. Nothing was queried.", "warn");
      return false;
    }
    return true;
  }

  function addNotice(text, kind = "info") {
    const node = document.createElement("div");
    node.className = "notice";
    node.dataset.kind = kind;
    node.textContent = text;
    $("#timeline").append(node);
    node.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function markPlanStep(index, status) {
    const li = $(`#plan-list li[data-index="${index}"]`);
    if (!li) return;
    li.dataset.state = status;
    $(".tick", li).textContent = status === "running" ? "[~]" : "[x]";
  }

  function openToolCard(tool, body) {
    const card = document.createElement("div");
    card.className = "tool-card";
    card.dataset.state = "running";
    card.innerHTML = `
      <div class="tool-head">
        <span class="spinner"></span>
        <span class="tool-name">${escapeHtml(tool)}</span>
        <span class="tool-meta">running</span>
      </div>
      <div class="tool-arg">${escapeHtml(body)}</div>`;
    $("#timeline").append(card);
    card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return card;
  }

  function closeToolCard(card, { meta, note, failed = false }) {
    card.dataset.state = failed ? "failed" : "done";
    const tick = document.createElement("span");
    tick.className = "tick";
    tick.textContent = failed ? "✕" : "✓";
    tick.style.cssText = `color:var(--${failed ? "bad" : "good"});font-family:var(--mono);font-size:12px`;
    $(".spinner", card)?.replaceWith(tick);
    $(".tool-meta", card).textContent = meta;
    if (note) {
      const el = document.createElement("div");
      el.className = "tool-note";
      el.textContent = note;
      card.append(el);
    }
  }

  /* ------------------------------------------------------ run an investigation ---- */

  async function investigate(task, { scroll = true } = {}) {
    const mine = ++state.runToken;
    if (scroll) revealStage();
    const alive = () => mine === state.runToken;

    resetStage(task.question);
    $("#demo-caption").textContent =
      "Running now. Each query below is sent to the real read-only database.";

    await renderPlan(task.plan, alive);
    if (!alive()) return;
    if (!(await awaitApproval(task.plan, alive))) return;

    const results = {};
    let derived = null;

    for (const step of task.steps) {
      if (!alive()) return;
      markPlanStep(step.step, "running");

      if (step.sql) {
        const card = openToolCard("sql_query", step.sql);
        const started = performance.now();
        let result;
        try {
          result = await runSqlOnServer(step.sql);
        } catch (error) {
          closeToolCard(card, { meta: "failed", note: error.message, failed: true });
          addNotice("The investigation stopped because a query failed.", "bad");
          return;
        }
        if (!alive()) return;

        if (result.refused || !result.ok) {
          closeToolCard(card, { meta: "refused", note: result.reason, failed: true });
          addNotice("The SQL guard refused a query, so the run cannot continue.", "bad");
          return;
        }
        results[step.key] = result;
        // Each query result becomes a citable source, with its real SQL and real rows.
        registerSqlSource(task, step.key, result);
        derived = task.derive(results);
        closeToolCard(card, {
          meta: `${result.row_count} rows · ${result.latency_ms} ms`,
          note: describeRows(result),
        });
      } else {
        const body = typeof step.display === "function" ? step.display(derived || {}) : step.display;
        const card = openToolCard(step.tool, body);
        await sleep(620);
        if (!alive()) return;
        closeToolCard(card, {
          meta: step.tool === "calculator" ? "2 ms" : "recorded fixture",
          note: step.note ? step.note(derived || {}) : "",
        });
      }

      markPlanStep(step.step, "done");
      await sleep(240);
    }

    if (!alive() || !derived) return;
    for (const [id, source] of Object.entries(TASKS.docSources)) {
      state.sources[id] = source;
    }
    await sleep(360);
    renderReport(task.report(derived));
  }

  function registerSqlSource(task, key, result) {
    // Source ids are positional per task, matching the [S#]/[L#]/[C#] markers in its report.
    const idByKey = {
      quarters: "S1",
      churn: "S3",
      lines: "L1",
      campaigns: "C1",
    };
    const id = idByKey[key];
    if (!id) return;
    const header = result.columns.join(" | ");
    const divider = "-".repeat(Math.min(header.length, 90));
    const rows = result.rows
      .slice(0, 25)
      .map((row) => result.columns.map((c) => formatCell(row[c])).join(" | "))
      .join("\n");
    state.sources[id] = {
      title: `${id} — sql_query (read-only, ${result.latency_ms} ms)`,
      body: `${result.executed_sql}\n\n${header}\n${divider}\n${rows}`,
    };
  }

  function describeRows(result) {
    if (!result.rows.length) return "The query returned no rows.";
    const first = result.rows[0];
    const shown = result.columns
      .slice(0, 3)
      .map((c) => `${c}=${formatCell(first[c])}`)
      .join(", ");
    return `${result.row_count} rows. First: ${shown}`;
  }

  function renderReport(report) {
    const node = $("#report");
    const chart = report.chart ? buildChart(report.chart) : "";
    node.innerHTML = `
      <header class="report-head">
        <h3>${escapeHtml(report.title)}</h3>
        <span class="badge badge-good">${Math.round(report.score * 100)}% of claims verified</span>
      </header>
      <p class="report-hint">Click any yellow tag to see exactly where that number came from.</p>
      ${report.html}
      ${chart}
      <p class="limitation">Worth knowing: ${escapeHtml(report.limitation)}</p>`;
    node.hidden = false;
    node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    $("#demo-caption").textContent =
      "Finished. Every figure above was computed from the query results shown in the timeline.";
  }

  function buildChart(spec) {
    const peak = Math.max(...spec.rows.flatMap((r) => [r.a, r.b])) || 1;
    const money = TASKS.helpers.money;
    const bars = spec.rows
      .map(
        (row) => `
        <div class="chart-row">
          <span>${escapeHtml(row.label)}</span>
          <div class="chart-bars">
            <div class="chart-bar" style="width:${(row.a / peak) * 100}%"><span>${money(row.a)}</span></div>
            <div class="chart-bar alt" style="width:${(row.b / peak) * 100}%"><span>${escapeHtml(row.bLabel || money(row.b))}</span></div>
          </div>
        </div>`,
      )
      .join("");
    return `
      <p class="chart-title">${escapeHtml(spec.label)}</p>
      <div class="chart" id="chart">
        ${bars}
        <div class="chart-legend">
          <span><i style="background:var(--accent)"></i>${escapeHtml(spec.legend[0])}</span>
          <span><i style="background:var(--accent-dim)"></i>${escapeHtml(spec.legend[1])}</span>
        </div>
      </div>`;
  }

  function formatCell(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "number") {
      return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
    }
    return String(value);
  }

  /* ------------------------------------------------------------ ask the box ---- */

  function initAsk() {
    const suggestions = $("#ask-suggestions");
    for (const task of TASKS.tasks) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "suggestion";
      button.textContent = task.short;
      button.addEventListener("click", () => {
        $("#question-input").value = task.question;
        submitQuestion();
      });
      suggestions.append(button);
    }
    $("#ask-btn").addEventListener("click", submitQuestion);
    $("#question-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submitQuestion();
      }
    });
  }

  async function submitQuestion() {
    const question = $("#question-input").value.trim();
    if (!question) {
      toast("Type a question first, or pick one of the suggestions.", "error");
      return;
    }
    if (!state.token) {
      toast("Click “Try the demo” at the top to sign in first.", "error");
      return;
    }

    const task = TASKS.tasks.find((candidate) => candidate.matches(question));
    if (!task) {
      revealStage();
      if (state.research?.enabled) {
        await askRealModel(question);
      } else {
        explainScriptedLimit(question);
        toast("That question needs a real language model. See the explanation below.", "error");
      }
      return;
    }
    revealStage();
    toast("Planning the investigation…", "success");
    await investigate(task);
  }

  // Two different reasons a question cannot be answered, and they deserve different messages.
  // Asking about data that does not exist is not a model limitation, and saying "configure a
  // language model" to someone asking about headcount would be actively misleading.
  const KNOWN_SUBJECTS =
    /revenue|sales|order|customer|product|margin|campaign|marketing|spend|region|emea|apac|americas|currency|exchange|churn|price|discount/i;

  function explainScriptedLimit(question) {
    ++state.runToken;
    resetStage(question);

    const outOfScope = !KNOWN_SUBJECTS.test(question);
    $("#demo-caption").textContent = outOfScope
      ? "That subject is not in this database."
      : "This question needs a real language model.";

    const scopeBlock = `
      <p><strong style="display:inline">What this database holds:</strong> sales orders and order
      lines, customers and the countries they are in, products and product lines with their
      margins, and monthly marketing spend by campaign. Two years of it.</p>
      <p>There is no HR, headcount, payroll or recruitment data, so no amount of model capability
      would answer a question about hiring. Connecting a new data source is how that changes.</p>`;

    const modelBlock = `
      <p>
        It answers three questions exactly, with no API key and no internet connection, which is
        also how the 95 automated tests run. It cannot answer an arbitrary question, by design.
      </p>
      <p>To ask anything you like, set these and restart the server:</p>
      <pre>LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_API_KEY=gsk_...            # free tier
OPENAI_MODEL=llama-3.3-70b-versatile</pre>
      <p>
        Or keep it on your own machine with Ollama so no data leaves your network:
        <code>OPENAI_BASE_URL=http://localhost:11434/v1</code>, where no key is needed.
      </p>`;

    $("#timeline").innerHTML = `
      <div class="notice" data-kind="warn">
        <strong>${
          outOfScope
            ? "This demo database has no data on that."
            : "This demo is running on a built-in scripted model."
        }</strong>
        ${outOfScope ? scopeBlock : modelBlock}
        <p class="muted">Try one of the three suggested questions, which do work end to end.</p>
      </div>`;
  }

  async function askRealModel(question) {
    const mine = ++state.runToken;
    const alive = () => mine === state.runToken;

    resetStage(question);
    $("#demo-caption").textContent = `Asking ${state.research.model}. It writes the SQL; the guard decides whether it runs.`;
    const thinking = openToolCard("planning", `question: ${question}

The model is being given the database schema and asked for a plan and the SQL to answer it.`);

    let answer;
    try {
      answer = await api("/research/ask", { method: "POST", body: { question } });
    } catch (error) {
      closeToolCard(thinking, { meta: "failed", note: error.message, failed: true });
      addNotice(error.message, "bad");
      return;
    }
    if (!alive()) return;

    closeToolCard(thinking, {
      meta: `${answer.elapsed_ms} ms · ${answer.tokens} tokens · $${answer.cost_usd.toFixed(4)}`,
      note: answer.plan.length ? `Plan: ${answer.plan.join(" → ")}` : "",
    });

    for (const [index, step] of answer.plan.entries()) {
      const li = document.createElement("li");
      li.dataset.state = "done";
      li.dataset.index = String(index);
      li.innerHTML = `<span class="tick">[x]</span><span>${escapeHtml(step)}</span>`;
      $("#plan-list").append(li);
    }

    if (!answer.answerable) {
      addNotice(answer.message, "warn");
      $("#demo-caption").textContent = "The model could not answer this from the available data.";
      return;
    }

    for (const step of answer.steps) {
      if (!alive()) return;
      const card = openToolCard("sql_query", step.executed_sql || step.sql);
      await sleep(420);
      if (step.ok) {
        state.sources[step.source_id] = {
          title: `${step.source_id} — sql_query (read-only, ${step.latency_ms} ms)`,
          body: renderSourceBody(step),
        };
        closeToolCard(card, {
          meta: `${step.row_count} rows · ${step.latency_ms} ms`,
          note: step.purpose,
        });
      } else {
        closeToolCard(card, {
          meta: step.refused ? "refused by the guard" : "failed",
          note: step.reason,
          failed: true,
        });
      }
    }

    if (!alive()) return;
    const removed = answer.removed_claims.length
      ? `<p class="limitation">Verification removed ${answer.removed_claims.length} sentence${answer.removed_claims.length === 1 ? "" : "s"} that the evidence did not support.</p>`
      : "";
    const paragraphs = answer.body
      .split(/\n+/)
      .filter((p) => p.trim())
      .map((p) => `<p>${linkCitations(p)}</p>`)
      .join("");

    const report = $("#report");
    report.innerHTML = `
      <header class="report-head">
        <h3>${escapeHtml(answer.title)}</h3>
        <span class="badge ${answer.verification_score >= 0.8 ? "badge-good" : "badge-warn"}">
          ${Math.round(answer.verification_score * 100)}% of claims verified
        </span>
      </header>
      <p class="report-hint">
        Written by ${escapeHtml(answer.model)}. Click any yellow tag for the query behind it.
      </p>
      ${paragraphs}
      ${removed}
      <p class="limitation">Worth knowing: ${escapeHtml(answer.limitation || "Based only on the queries shown above.")}</p>`;
    report.hidden = false;
    report.scrollIntoView({ block: "nearest", behavior: "smooth" });
    $("#demo-caption").textContent = `Answered in ${(answer.elapsed_ms / 1000).toFixed(1)}s for $${answer.cost_usd.toFixed(4)}.`;
  }

  // Lay the rows out as a fixed-width table for the source panel.
  function renderSourceBody(step) {
    const header = step.columns.join(" | ");
    const divider = "-".repeat(Math.min(header.length, 90));
    const rows = step.rows
      .slice(0, 25)
      .map((row) => step.columns.map((c) => formatCell(row[c])).join(" | "))
      .join("\n");
    return [step.executed_sql, "", header, divider, rows].join("\n");
  }

  // Turn [S1] markers into clickable chips without trusting the model's text as HTML.
  function linkCitations(text) {
    return escapeHtml(text).replace(
      /\[S(\d+)\]/g,
      (_, n) => `<cite data-src="S${n}">S${n}</cite>`,
    );
  }

  /* ---------------------------------------------------------- citations ---- */

  function initCitations() {
    document.addEventListener("click", (event) => {
      const chip = event.target.closest("cite[data-src]");
      if (!chip) return;
      const source = state.sources[chip.dataset.src];
      if (!source) {
        toast("That source is only available after the investigation runs.", "info");
        return;
      }
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
    $("#ask-hint").textContent = "Press Enter to investigate";
    $("#pg-hint").textContent = "Queries run against the read-only database";
    $("#run-sql").disabled = false;
    $("#ask-btn").disabled = false;
    loadProviders();
    loadLiveStats();
    loadResearchStatus();
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
      // An expired token is not worth reporting; it only means signing in again.
      state.token = null;
      sessionStorage.removeItem("meridian.token");
      $("#run-sql").disabled = true;
    }
  }

  /* ------------------------------------------------------------ playground ---- */

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
      label: "Which ad campaigns waste money",
      kind: "ok",
      sql: `SELECT campaign, ROUND(SUM(spend_usd)) AS spend,
       ROUND(SUM(attributed_revenue_usd) / SUM(spend_usd), 2) AS return_per_dollar
FROM marketing_spend
GROUP BY campaign`,
    },
    {
      group: "Normal business questions",
      label: 'A safe query containing the word "delete"',
      kind: "ok",
      sql: "WITH delete_me AS (SELECT id FROM orders) SELECT COUNT(*) AS n FROM delete_me",
    },
    {
      group: "Attempts to do damage",
      label: "Destroy the orders table",
      kind: "attack",
      sql: "DROP TABLE orders",
    },
    {
      group: "Attempts to do damage",
      label: "Delete every order",
      kind: "attack",
      sql: "DELETE FROM orders",
    },
    {
      group: "Attempts to do damage",
      label: "Set all revenue to zero",
      kind: "attack",
      sql: "UPDATE orders SET subtotal_usd = 0",
    },
    {
      group: "Attempts to do damage",
      label: "Sneak a second command in",
      kind: "attack",
      sql: "SELECT 1; DROP TABLE orders",
    },
    {
      group: "Attempts to do damage",
      label: "Read the user accounts table",
      kind: "attack",
      sql: "SELECT * FROM users",
    },
    {
      group: "Attempts to do damage",
      label: "Load code from a file",
      kind: "attack",
      sql: "SELECT load_extension('evil.dll')",
    },
    {
      group: "Attempts to do damage",
      label: "Probe the database internals",
      kind: "attack",
      sql: "PRAGMA table_info(orders)",
    },
  ];

  function initPlayground() {
    const presets = $("#pg-presets");
    let currentGroup = null;
    for (const preset of PRESETS) {
      if (preset.group !== currentGroup) {
        currentGroup = preset.group;
        const label = document.createElement("p");
        label.className = "pg-group-label";
        label.textContent = currentGroup;
        presets.append(label);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pg-preset";
      button.dataset.kind = preset.kind;
      button.textContent = preset.label;
      button.addEventListener("click", () => {
        $("#sql-input").value = preset.sql;
        runPlaygroundSql();
      });
      presets.append(button);
    }
    $("#run-sql").addEventListener("click", runPlaygroundSql);
    $("#sql-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) runPlaygroundSql();
    });
  }

  async function runPlaygroundSql() {
    const sql = $("#sql-input").value.trim();
    const panel = $("#pg-result");
    if (!sql) return;
    if (!state.token) {
      toast("Click “Try the demo” at the top to sign in first.", "error");
      return;
    }
    panel.innerHTML = '<p class="muted">Running…</p>';
    try {
      const result = await runSqlOnServer(sql);
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
    return `<div class="refusal"><h4>${heading}</h4>${guardrail}<p class="muted">${escapeHtml(result.reason)}</p></div>`;
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
        <span>row cap ${result.limit_applied ?? "-"}</span>
        <span>tables: ${escapeHtml(result.referenced_tables.join(", ") || "-")}</span>
      </div>
      <div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  /* ---------------------------------------------------------- status panel ---- */

  const STATUS = [
    ["Ask a question, get a cited answer", true],
    ["Plan approval before anything runs", true],
    ["Read-only SQL guard", true],
    ["Live queries against the database", true],
    ["Clickable sources on every number", true],
    ["Charts built from query results", true],
    ["Sign-in and permissions", true],
    ["Document search and injection flagging", true],
    ["95 automated tests, fully offline", true],
    ["Real language model support", false],
    ["Background worker and crash recovery", false],
    ["Live streaming while a run is in progress", false],
    ["Saved run history and sharing", false],
    ["Docker and continuous integration", false],
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

  async function loadResearchStatus() {
    try {
      state.research = await api("/research/status");
    } catch {
      state.research = { enabled: false };
    }
    const hint = $("#ask-hint");
    if (state.research.enabled) {
      hint.textContent = `Ask anything — answered by ${state.research.model}`;
      $("#question-input").placeholder = "Ask anything about sales, products, customers or marketing spend";
    } else {
      hint.textContent = "Press Enter to investigate";
    }
  }

  async function loadProviders() {
    try {
      const providers = await api("/datasources/providers");
      const rows = [
        `model: ${providers.model}`,
        `embeddings: ${providers.embedding_provider}`,
        `external tools: ${providers.tools_mode}`,
        `queue: ${providers.queue}`,
        providers.fully_offline ? "no network access" : "network enabled",
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
      if (orders) $('[data-stat="orders"]').textContent = orders.row_count.toLocaleString();
    } catch {
      // Keep whatever figure the markup already shows.
    }
  }

  /* ----------------------------------------------------------------- boot ---- */

  async function boot() {
    initTheme();
    initStatus();
    initCitations();
    initPlayground();
    initAsk();
    $("#try-demo").addEventListener("click", () => signInDemo("admin"));
    $("#hero-demo").addEventListener("click", () => signInDemo("analyst"));
    $("#replay-run").addEventListener("click", () => {
      $("#question-input").value = TASKS.tasks[0].question;
      submitQuestion();
    });

    await restoreSession();
    // Sign in automatically so the page demonstrates itself on first load rather than showing an
    // empty shell behind a sign-in wall.
    if (!state.token) await signInDemo("analyst");
    if (state.token) await investigate(TASKS.tasks[0], { scroll: false });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
