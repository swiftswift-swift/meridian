/* Runs history and the saved run detail view. */

import { runs } from "../api.js";
import { navigate, pageHeader } from "../shell.js";
import {
  $,
  duration,
  emptyState,
  errorState,
  escapeHtml,
  scoreBadge,
  since,
  skeleton,
  statusBadge,
  table,
  toast,
} from "../ui.js";
import { bindExportActions, exportActions } from "../export.js";
import { chartSpec } from "../format.js";
import { barChart } from "../ui.js";
import { linkCitations } from "./research.js";

function renderSavedFinding(observation) {
  const spec = chartSpec(observation.columns, observation.rows);
  const chart = spec ? barChart(spec.rows, { legend: spec.legend }) : "";
  return `${chart}${table(observation.columns, observation.rows, { limit: 15 })}`;
}

export async function runsPage(view) {
  view.innerHTML = `
    ${pageHeader({
      title: "Past answers",
      lede: "Every question you have asked, newest first. Answers stay readable, with their workings, long afterwards.",
      actions: '<a class="btn btn-primary" href="/app/new" data-link>Ask a question</a>',
    })}
    <section class="panel">
      <div class="list-toolbar">
        <input type="search" id="filter" placeholder="Search your past questions" aria-label="Filter runs" />
        <select id="status-filter" aria-label="Filter by status">
          <option value="">Show everything</option>
          <option value="completed">Answered</option>
          <option value="failed">No answer found</option>
        </select>
      </div>
      <div id="list">${skeleton(4)}</div>
      <div class="list-foot"><button class="btn btn-ghost" id="more" hidden>Load more</button></div>
    </section>`;

  let items = [];
  let cursor = null;

  async function load(initial = false) {
    try {
      const page = await runs.list(initial ? null : cursor);
      items = initial ? page.items : items.concat(page.items);
      cursor = page.next_cursor;
      $("#more").hidden = !cursor;
      paint();
    } catch (error) {
      $("#list").innerHTML = errorState(error);
      $("#list").querySelector("[data-retry]")?.addEventListener("click", () => load(true));
    }
  }

  function paint() {
    const needle = $("#filter").value.trim().toLowerCase();
    const status = $("#status-filter").value;
    const filtered = items.filter((item) => {
      const matchesText =
        !needle ||
        item.question.toLowerCase().includes(needle) ||
        (item.title || "").toLowerCase().includes(needle);
      return matchesText && (!status || item.status === status);
    });

    if (!filtered.length) {
      $("#list").innerHTML = items.length
        ? emptyState({ title: "Nothing matches that", body: "Try different words, or clear the filter." })
        : emptyState({
            title: "You have not asked anything yet",
            body: "Ask your first question and the answer will be saved here, with everything it looked up.",
            actionLabel: "Ask a question",
            actionHref: "/app/new",
          });
      return;
    }

    $("#list").innerHTML = `
      <ul class="run-list">
        ${filtered
          .map(
            (item) => `
          <li>
            <a class="run-row" href="/app/runs/${encodeURIComponent(item.id)}" data-link>
              <div class="run-main">
                <strong>${escapeHtml(item.title || item.question)}</strong>
                <span class="run-question">${escapeHtml(item.question)}</span>
              </div>
              <div class="run-stats">
                ${statusBadge(item.status)}
                ${item.status === "completed" ? scoreBadge(item.verification_score) : ""}
                <span>${item.query_count} search${item.query_count === 1 ? "" : "es"}</span>
                <span>${duration(item.duration_ms)}</span>
                <span>$${item.cost_usd.toFixed(4)}</span>
                <span class="run-age">${escapeHtml(since(item.created_at))}</span>
              </div>
            </a>
          </li>`,
          )
          .join("")}
      </ul>`;
  }

  $("#filter").addEventListener("input", paint);
  $("#status-filter").addEventListener("change", paint);
  $("#more").addEventListener("click", () => load(false));
  await load(true);
}

export async function runDetailPage(view, params) {
  view.innerHTML = `${pageHeader({ title: "Answer", lede: "Loading…" })}<div class="panel">${skeleton(5)}</div>`;

  let run;
  try {
    run = await runs.get(params.id);
  } catch (error) {
    view.innerHTML = `${pageHeader({ title: "Answer" })}<div class="panel">${errorState(error, "Back to runs")}</div>`;
    view.querySelector("[data-retry]")?.addEventListener("click", () => navigate("/app/runs"));
    return;
  }

  const report = run.report;
  const usage = run.usage || {};

  view.innerHTML = `
    ${pageHeader({
      title: report?.title || run.question,
      lede: run.question,
      actions: `
        <button class="btn btn-ghost" id="share">Copy share link</button>
        ${exportActions()}
        <button class="btn btn-ghost" id="rerun">Ask again</button>
        <button class="btn btn-ghost danger" id="delete">Delete</button>`,
    })}

    <div class="run-meta">
      ${statusBadge(run.status)}
      ${report ? scoreBadge(report.verification_score) : ""}
      <span>${duration((usage.wall_seconds || 0) * 1000)}</span>
      <span>${(usage.tokens || 0).toLocaleString()} tokens</span>
      <span>$${Number(usage.cost_usd || 0).toFixed(4)}</span>
      <span>${escapeHtml(usage.model || "")}</span>
      <span>${escapeHtml(since(run.created_at))}</span>
    </div>

    ${
      run.plan?.length
        ? `<section class="panel"><h3 class="panel-title">Plan</h3>
             <ol class="plan-list">${run.plan.map((p) => `<li><span class="tick">✓</span>${escapeHtml(p)}</li>`).join("")}</ol>
           </section>`
        : ""
    }

    ${
      report
        ? `<article class="panel report-panel">
             <h3 class="panel-title">The answer</h3>
             <div class="report-body">${report.body
               .split(/\n+/)
               .filter((p) => p.trim())
               .map((p) => `<p>${linkCitations(p)}</p>`)
               .join("")}</div>
             ${
               (report.removed_claims || []).length
                 ? `<p class="limitation">Verification removed ${report.removed_claims.length} unsupported sentence(s).</p>`
                 : ""
             }
             ${(report.limitations || []).map((l) => `<p class="limitation">Worth knowing: ${escapeHtml(l)}</p>`).join("")}
           </article>`
        : `<div class="panel"><p class="muted">${escapeHtml(run.error || "This run produced no report.")}</p></div>`
    }

    <section class="panel">
      <h3 class="panel-title">Where these numbers came from</h3>
      <p class="field-hint">Every search it ran on your data. Click one to see the rows it found.</p>
      ${run.observations
        .map(
          (observation) => `
        <details class="query-card" data-state="${!observation.ok ? "refused" : observation.row_count === 0 ? "empty" : "ok"}" id="src-${escapeHtml(observation.source_id)}">
          <summary>
            <svg class="chev" viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 2l4 4-4 4"/></svg>
            <span class="src">${escapeHtml(observation.source_id)}</span>
            <span class="purpose">${escapeHtml(observation.purpose)}</span>
            <span class="meta">${
              !observation.ok
                ? "blocked for safety"
                : observation.row_count === 0
                  ? "No data found"
                  : `${observation.row_count} row${observation.row_count === 1 ? "" : "s"} found`
            }</span>
          </summary>
          <pre class="sql">${escapeHtml(observation.sql)}</pre>
          ${observation.ok ? renderSavedFinding(observation) : `<p class="refusal-text">${escapeHtml(observation.reason)}</p>`}
        </details>`,
        )
        .join("")}
    </section>`;

  view.addEventListener("click", (event) => {
    const chip = event.target.closest("cite[data-src]");
    if (!chip) return;
    const target = view.querySelector(`#src-${CSS.escape(chip.dataset.src)}`);
    if (target) {
      target.open = true;
      target.scrollIntoView({ block: "center", behavior: "smooth" });
      target.classList.add("flash");
      setTimeout(() => target.classList.remove("flash"), 900);
    }
  });

  bindExportActions(view, {
    title: report?.title || run.question,
    question: run.question,
    body: report?.body || run.error || "",
    verification_score: report?.verification_score ?? 0,
    removed_claims: report?.removed_claims || [],
    limitations: report?.limitations || [],
    observations: run.observations,
    usage: run.usage,
  });

  $("#share").addEventListener("click", async () => {
    try {
      const { url } = await runs.share(params.id);
      await navigator.clipboard.writeText(url);
      toast("Link copied. Anyone you send it to can read this answer without signing in.", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  });

  $("#rerun").addEventListener("click", () => {
    sessionStorage.setItem("meridian.prefill", run.question);
    navigate("/app/new");
  });

  $("#delete").addEventListener("click", async () => {
    if (!confirm("Delete this answer and everything it looked up? This cannot be undone.")) return;
    try {
      await runs.remove(params.id);
      toast("Answer deleted.", "success");
      navigate("/app/runs");
    } catch (error) {
      toast(error.message, "error");
    }
  });
}
