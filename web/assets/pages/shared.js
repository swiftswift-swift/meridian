/* A read-only report, opened from a share link.

   No authentication: the unguessable token is the credential. That is the point of sharing a
   report with someone who has no account. */

import { escapeHtml, scoreBadge, since, table } from "../ui.js";
import { linkCitations } from "./research.js";

export async function sharedReportPage(root, params) {
  root.innerHTML = `<div class="shared-page"><div class="panel">Loading the report…</div></div>`;

  let run;
  try {
    const response = await fetch(`/api/v1/shared/${encodeURIComponent(params.token)}`);
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.detail || "That share link is not valid.");
    }
    run = await response.json();
  } catch (error) {
    root.innerHTML = `
      <div class="shared-page">
        <div class="panel">
          <h1>This link does not work</h1>
          <p class="muted">${escapeHtml(error.message)}</p>
          <a class="btn btn-primary" href="/" data-link>Go to Meridian</a>
        </div>
      </div>`;
    return;
  }

  const report = run.report;
  const usage = run.usage || {};

  root.innerHTML = `
    <div class="shared-page">
      <header class="shared-head">
        <a class="brand" href="/" data-link>
          <span class="brand-mark" aria-hidden="true"></span>
          <span class="brand-name">Meridian</span>
        </a>
        <span class="badge badge-warn">Shared report, read only</span>
      </header>

      <article class="panel report-panel">
        <h1>${escapeHtml(report?.title || run.question)}</h1>
        <p class="page-lede">${escapeHtml(run.question)}</p>
        <div class="run-meta">
          ${report ? scoreBadge(report.verification_score) : ""}
          <span>${(usage.tokens || 0).toLocaleString()} tokens</span>
          <span>$${Number(usage.cost_usd || 0).toFixed(4)}</span>
          <span>${escapeHtml(since(run.created_at))}</span>
        </div>
        ${
          report
            ? `<div class="report-body">${report.body
                .split(/\n+/)
                .filter((p) => p.trim())
                .map((p) => `<p>${linkCitations(p)}</p>`)
                .join("")}</div>
               ${(report.limitations || []).map((l) => `<p class="limitation">Worth knowing: ${escapeHtml(l)}</p>`).join("")}`
            : `<p class="muted">${escapeHtml(run.error || "This run produced no report.")}</p>`
        }
      </article>

      <section class="panel">
        <h3 class="panel-title">Evidence</h3>
        <p class="field-hint">Every query behind the answer above, with the rows it returned.</p>
        ${run.observations
          .map(
            (observation) => `
          <details class="query-card" id="src-${escapeHtml(observation.source_id)}">
            <summary>
              <span class="src">${escapeHtml(observation.source_id)}</span>
              <span class="purpose">${escapeHtml(observation.purpose)}</span>
              <span class="meta">${observation.row_count} rows</span>
            </summary>
            <pre class="sql">${escapeHtml(observation.sql)}</pre>
            ${table(observation.columns, observation.rows, { limit: 15 })}
          </details>`,
          )
          .join("")}
      </section>

      <footer class="shared-foot">
        <p class="muted">
          Every figure above is traceable to the query that produced it. Nothing in this report was
          written without evidence behind it.
        </p>
      </footer>
    </div>`;

  root.addEventListener("click", (event) => {
    const chip = event.target.closest("cite[data-src]");
    if (!chip) return;
    const target = root.querySelector(`#src-${CSS.escape(chip.dataset.src)}`);
    if (target) {
      target.open = true;
      target.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  });
}
