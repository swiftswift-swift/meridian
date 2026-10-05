/* New research: ask a question and watch the investigation run. */

import { research, runs, session } from "../api.js";
import { navigate, pageHeader } from "../shell.js";
import { $, escapeHtml, duration, escapeHtml as esc, scoreBadge, table, toast } from "../ui.js";

const SUGGESTIONS = [
  "Why did EMEA revenue drop in Q3 compared to Q2?",
  "Which product line should we prioritise next quarter?",
  "Is any marketing campaign wasting money?",
  "Which country generates the most revenue?",
  "Which customer has the highest lifetime revenue?",
];

const PRESETS = {
  quick: { label: "Quick", detail: "4 steps, ~30s" },
  standard: { label: "Standard", detail: "8 steps, ~2min" },
  deep: { label: "Deep", detail: "14 steps, ~5min" },
};

export async function researchPage(view) {
  let status = { enabled: false, model: "scripted-demo" };
  try {
    status = await research.status();
  } catch {
    // The page still works for the built-in questions without the live model.
  }

  const canRun = session.user?.role !== "viewer";

  view.innerHTML = `
    ${pageHeader({
      title: "New research",
      lede: "Ask a question in plain English. It plans, queries the database and writes a cited answer.",
    })}

    <section class="panel ask-panel">
      <label class="field-label" for="question">Your question</label>
      <textarea id="question" rows="3" placeholder="Why did EMEA revenue drop in Q3 compared to Q2?"
        ${canRun ? "" : "disabled"}></textarea>

      <div class="ask-controls">
        <fieldset class="preset-group">
          <legend>Budget</legend>
          ${Object.entries(PRESETS)
            .map(
              ([key, preset], index) => `
            <label class="preset">
              <input type="radio" name="preset" value="${key}" ${index === 1 ? "checked" : ""} />
              <span><strong>${preset.label}</strong><em>${preset.detail}</em></span>
            </label>`,
            )
            .join("")}
        </fieldset>

        <fieldset class="tool-group">
          <legend>Tools</legend>
          <label class="check"><input type="checkbox" checked disabled /> <span>SQL database</span></label>
          <label class="check"><input type="checkbox" id="tool-kb" checked /> <span>Internal documents</span></label>
          <label class="check"><input type="checkbox" id="tool-web" /> <span>Web search</span></label>
          <label class="check"><input type="checkbox" id="ask-first" checked /> <span>Ask before using web tools</span></label>
        </fieldset>
      </div>

      <div class="ask-actions">
        <button class="btn btn-primary btn-lg" id="go" type="button" ${canRun ? "" : "disabled"}>
          Investigate
        </button>
        <span class="muted" id="model-note">
          ${
            canRun
              ? status.enabled
                ? `Answered by ${esc(status.model)}`
                : "Built-in questions only. Configure a model to ask anything."
              : "The viewer role can read research but not start runs."
          }
        </span>
      </div>

      <p class="field-hint">Suggestions</p>
      <div class="chips" id="suggestions">
        ${SUGGESTIONS.map((q) => `<button class="chip" type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("")}
      </div>
    </section>

    <section id="stage" class="stage" hidden></section>`;

  $("#suggestions").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-q]");
    if (!chip) return;
    $("#question").value = chip.dataset.q;
    start();
  });
  $("#go").addEventListener("click", start);
  $("#question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      start();
    }
  });

  let running = false;

  async function start() {
    const question = $("#question").value.trim();
    if (!question) {
      toast("Type a question, or pick a suggestion.", "error");
      return;
    }
    if (running) return;
    running = true;
    $("#go").disabled = true;
    $("#go").textContent = "Investigating…";

    const stage = $("#stage");
    stage.hidden = false;
    stage.innerHTML = renderRunning(question);
    stage.scrollIntoView({ block: "start", behavior: "smooth" });

    try {
      const result = await runs.create(question);
      stage.innerHTML = renderResult(result);
      bindResult(stage, result);
    } catch (error) {
      stage.innerHTML = `
        <div class="panel">
          <h3 class="panel-title">The investigation could not run</h3>
          <p class="muted">${esc(error.message)}</p>
          ${
            error.status === 429
              ? '<p class="muted">The model provider is rate limiting. Wait about 30 seconds and try again.</p>'
              : ""
          }
        </div>`;
    } finally {
      running = false;
      $("#go").disabled = false;
      $("#go").textContent = "Investigate";
    }
  }
}

function renderRunning(question) {
  const stages = [
    "Reading the database schema",
    "Planning the investigation",
    "Checking each query against the SQL guard",
    "Running the approved queries",
    "Writing the answer from the rows returned",
    "Verifying every number against the evidence",
  ];
  return `
    <div class="panel">
      <h3 class="panel-title">${escapeHtml(question)}</h3>
      <ol class="live-stages">
        ${stages.map((s, i) => `<li style="animation-delay:${i * 0.45}s"><span class="spinner"></span>${escapeHtml(s)}</li>`).join("")}
      </ol>
    </div>`;
}

function renderResult(result) {
  if (!result.answerable) {
    return `
      <div class="panel">
        <h3 class="panel-title">No answer from the available data</h3>
        <p class="muted">${escapeHtml(result.message)}</p>
        ${
          result.plan?.length
            ? `<p class="field-hint">It had planned to:</p><ul class="plain-list">${result.plan.map((p) => `<li>${escapeHtml(p)}</li>`).join("")}</ul>`
            : ""
        }
      </div>`;
  }

  const meta = `
    <div class="run-meta">
      <span>${duration(result.elapsed_ms)}</span>
      <span>${result.steps.length} quer${result.steps.length === 1 ? "y" : "ies"}</span>
      <span>${result.tokens.toLocaleString()} tokens</span>
      <span>$${result.cost_usd.toFixed(4)}</span>
      <span>${escapeHtml(result.model)}</span>
    </div>`;

  const steps = result.steps
    .map((step) => {
      const ok = step.ok;
      return `
      <details class="query-card" data-state="${ok ? "ok" : step.refused ? "refused" : "failed"}">
        <summary>
          <span class="src">${escapeHtml(step.source_id)}</span>
          <span class="purpose">${escapeHtml(step.purpose)}</span>
          <span class="meta">${ok ? `${step.row_count} rows · ${step.latency_ms} ms` : step.refused ? "refused by the guard" : "failed"}</span>
        </summary>
        <pre class="sql">${escapeHtml(step.executed_sql || step.sql)}</pre>
        ${ok ? table(step.columns, step.rows, { limit: 12 }) : `<p class="refusal-text">${escapeHtml(step.reason)}</p>`}
      </details>`;
    })
    .join("");

  const removed = result.removed_claims.length
    ? `<p class="limitation">Verification removed ${result.removed_claims.length} sentence${result.removed_claims.length === 1 ? "" : "s"} the evidence did not support.</p>`
    : "";

  const body = result.body
    .split(/\n+/)
    .filter((p) => p.trim())
    .map((p) => `<p>${linkCitations(p)}</p>`)
    .join("");

  return `
    <article class="panel report-panel">
      <header class="report-head">
        <h2>${escapeHtml(result.title)}</h2>
        ${scoreBadge(result.verification_score)}
      </header>
      ${meta}
      <div class="report-body">${body}</div>
      ${removed}
      <p class="limitation">Worth knowing: ${escapeHtml(result.limitation || "Based only on the queries below.")}</p>
      <div class="report-actions">
        <a class="btn btn-ghost btn-sm" href="/app/runs/${encodeURIComponent(result.run_id)}" data-link>Open saved run</a>
        <button class="btn btn-ghost btn-sm" data-copy>Copy as Markdown</button>
      </div>
    </article>

    <section class="panel">
      <h3 class="panel-title">Evidence</h3>
      <p class="field-hint">Every query that ran, in order. Click one to see the rows.</p>
      ${steps}
    </section>`;
}

function bindResult(stage, result) {
  const copy = stage.querySelector("[data-copy]");
  if (copy) {
    copy.addEventListener("click", async () => {
      const markdown = `# ${result.title}\n\n${result.body}\n\n_Verification: ${Math.round(result.verification_score * 100)}%_\n`;
      try {
        await navigator.clipboard.writeText(markdown);
        toast("Copied to the clipboard.", "success");
      } catch {
        toast("The browser blocked clipboard access.", "error");
      }
    });
  }
  stage.addEventListener("click", (event) => {
    const chip = event.target.closest("cite[data-src]");
    if (!chip) return;
    const card = stage.querySelector(`.query-card [class="src"]`);
    const target = Array.from(stage.querySelectorAll(".query-card")).find(
      (node) => node.querySelector(".src")?.textContent === chip.dataset.src,
    );
    if (target) {
      target.open = true;
      target.scrollIntoView({ block: "center", behavior: "smooth" });
      target.classList.add("flash");
      setTimeout(() => target.classList.remove("flash"), 900);
    }
    void card;
  });
}

export function linkCitations(text) {
  return escapeHtml(text).replace(
    /\[S(\d+)\]/g,
    (_, n) => `<cite data-src="S${n}">S${n}</cite>`,
  );
}

export { navigate };
