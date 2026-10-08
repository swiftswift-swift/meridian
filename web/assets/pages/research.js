/* Ask a question. Written for someone who has never seen the product before. */

import { research, runs, session } from "../api.js";
import { pageHeader } from "../shell.js";
import { bindExportActions, exportActions } from "../export.js";
import { chartSpec } from "../format.js";
import { startTour } from "../tour.js";
import { $, barChart, duration, escapeHtml, table, toast } from "../ui.js";

const EXAMPLES = [
  {
    topic: "Understand a change",
    questions: [
      "Why did EMEA revenue drop in Q3 compared to Q2?",
      "Which region is growing fastest?",
      "Did revenue go up or down last quarter?",
    ],
  },
  {
    topic: "Decide where to invest",
    questions: [
      "Which product line should we prioritise next quarter?",
      "Which products grow fastest but earn the least?",
      "Is any marketing campaign wasting money?",
    ],
  },
  {
    topic: "Know your customers",
    questions: [
      "Which customer has the highest lifetime revenue?",
      "Which country generates the most revenue?",
      "Have we lost any big customers?",
    ],
  },
];

const DEPTH = [
  { key: "quick", label: "Fast answer", detail: "A couple of searches. Around 30 seconds." },
  { key: "standard", label: "Normal", detail: "Several searches and cross-checks. Around 2 minutes." },
  { key: "deep", label: "Dig deep", detail: "As many searches as it needs. Up to 5 minutes." },
];

export async function researchPage(view) {
  let status = { enabled: false, model: "built-in" };
  try {
    status = await research.status();
  } catch {
    // The page still works for the built-in questions without a live model.
  }

  const canRun = session.user?.role !== "viewer";
  const firstVisit = !localStorage.getItem("meridian.seenWelcome");
  const prefill = sessionStorage.getItem("meridian.prefill") || "";
  sessionStorage.removeItem("meridian.prefill");

  view.innerHTML = `
    ${
      firstVisit
        ? `<aside class="welcome" id="welcome">
             <div>
               <h2>Welcome. Here is the whole idea.</h2>
               <p>
                 Ask a question about the business the way you would ask a colleague. Meridian
                 looks through the company's sales records and documents, then writes you a short
                 answer. <strong>Every number it gives you can be clicked to see where it came
                 from.</strong> If it cannot prove something, it leaves it out rather than
                 guessing.
               </p>
               <p class="welcome-hint">Not sure what to ask? Pick one of the examples below.</p>
             </div>
             <button class="btn btn-ghost btn-sm" id="dismiss-welcome" type="button">Got it</button>
           </aside>`
        : ""
    }

    ${pageHeader({
      title: "Ask a question",
      lede: "Type it in plain English. You will get a short answer with its workings shown.",
    })}

    <section class="panel ask-panel">
      <label class="field-label" for="question">What would you like to know?</label>
      <textarea id="question" rows="3"
        placeholder="For example: why did our European sales fall last quarter?"
        ${canRun ? "" : "disabled"}>${escapeHtml(prefill)}</textarea>

      <details class="options">
        <summary>Options <span class="muted">(you can ignore these)</span></summary>
        <div class="ask-controls">
          <fieldset class="preset-group">
            <legend>How thorough should it be?</legend>
            ${DEPTH.map(
              (depth, index) => `
              <label class="preset">
                <input type="radio" name="depth" value="${depth.key}" ${index === 1 ? "checked" : ""} />
                <span><strong>${depth.label}</strong><em>${depth.detail}</em></span>
              </label>`,
            ).join("")}
          </fieldset>

          <fieldset class="tool-group">
            <legend>Where should it look?</legend>
            <label class="check"><input type="checkbox" checked disabled /> <span>Sales records <em class="muted">(always on)</em></span></label>
            <label class="check"><input type="checkbox" id="tool-kb" checked /> <span>Company documents and memos</span></label>
            <label class="check"><input type="checkbox" id="tool-web" /> <span>The public web</span></label>
            <label class="check"><input type="checkbox" id="ask-first" checked /> <span>Check with me before searching the web</span></label>
          </fieldset>
        </div>
      </details>

      <div class="ask-actions">
        <button class="btn btn-primary btn-lg" id="go" type="button" ${canRun ? "" : "disabled"}>
          Find out
        </button>
        <span class="muted" id="model-note">
          ${
            canRun
              ? status.enabled
                ? "Usually takes 3 to 10 seconds."
                : "The three example questions work. Others need a language model configured."
              : "Your account can read answers but not ask new questions. An admin can change that in Settings."
          }
        </span>
      </div>
    </section>

    <section class="panel examples-panel" id="examples">
      <h3 class="panel-title">Not sure what to ask?</h3>
      <p class="field-hint">These all work. Click one to try it.</p>
      ${EXAMPLES.map(
        (group) => `
        <div class="example-group">
          <h4>${escapeHtml(group.topic)}</h4>
          <div class="chips">
            ${group.questions.map((q) => `<button class="chip" type="button" data-q="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join("")}
          </div>
        </div>`,
      ).join("")}
    </section>

    <section id="stage" class="stage" hidden></section>`;

  const dismiss = $("#dismiss-welcome");
  if (dismiss) {
    dismiss.addEventListener("click", () => {
      localStorage.setItem("meridian.seenWelcome", "1");
      $("#welcome").remove();
    });
  }

  $("#examples").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-q]");
    if (!chip) return;
    $("#question").value = chip.dataset.q;
    start();
  });
  $("#go").addEventListener("click", start);
  if (sessionStorage.getItem("meridian.autorun") === "1") {
    sessionStorage.removeItem("meridian.autorun");
    start();
  } else {
    // Only offered on a quiet page: starting a tour over a running investigation is noise.
    const replay = sessionStorage.getItem("meridian.replayTour") === "1";
    sessionStorage.removeItem("meridian.replayTour");
    setTimeout(() => startTour({ force: replay }), 700);
  }
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
      toast("Type a question first, or pick one of the examples.", "error");
      $("#question").focus();
      return;
    }
    if (running) return;
    running = true;
    $("#go").disabled = true;
    $("#go").textContent = "Looking…";

    const stage = $("#stage");
    stage.hidden = false;
    stage.innerHTML = renderWorking(question);
    stage.scrollIntoView({ block: "start", behavior: "smooth" });

    try {
      const result = await runs.create(question);
      stage.innerHTML = renderAnswer(result);
      bindAnswer(stage, result);
      stage.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch (error) {
      stage.innerHTML = renderFailure(error);
      stage.querySelector("[data-retry]")?.addEventListener("click", start);
      countDown(stage.querySelector("[data-countdown]"));
    } finally {
      running = false;
      $("#go").disabled = false;
      $("#go").textContent = "Find out";
    }
  }
}

/* A visible countdown beats "try again later": the reader knows when to act. */
function countDown(node, seconds = 30) {
  if (!node) return;
  let left = seconds;
  node.textContent = `Ready to retry in ${left}s`;
  const timer = setInterval(() => {
    left -= 1;
    if (left <= 0) {
      clearInterval(timer);
      node.textContent = "You can try again now.";
      return;
    }
    node.textContent = `Ready to retry in ${left}s`;
  }, 1000);
}

function renderWorking(question) {
  const stages = [
    "Working out what to look up",
    "Checking each search is safe to run",
    "Searching the sales records",
    "Writing the answer",
    "Checking every number against the data",
  ];
  return `
    <div class="panel working">
      <h3 class="panel-title">${escapeHtml(question)}</h3>
      <ol class="live-stages">
        ${stages
          .map(
            (s, i) =>
              `<li style="animation-delay:${i * 0.5}s"><span class="spinner"></span>${escapeHtml(s)}</li>`,
          )
          .join("")}
      </ol>
      <p class="field-hint">This usually takes a few seconds.</p>
    </div>`;
}

function renderFailure(error) {
  const rateLimited = error.status === 429;
  const advice = rateLimited
    ? "The AI service is busy. It usually clears in about thirty seconds."
    : "Try rewording the question, or pick one of the examples above.";
  return `
    <div class="panel failure-panel">
      <h3 class="panel-title">That did not work</h3>
      <p class="plain-answer">${escapeHtml(error.message)}</p>
      <p class="muted">${escapeHtml(advice)}</p>
      <div class="report-actions">
        <button class="btn btn-primary btn-sm" data-retry>Try again</button>
        ${rateLimited ? '<span class="muted" data-countdown></span>' : ""}
      </div>
    </div>`;
}

function renderAnswer(result) {
  if (!result.answerable) {
    return `
      <div class="panel">
        <h3 class="panel-title">I could not answer that from this data</h3>
        <p class="plain-answer">${escapeHtml(result.message)}</p>
        <p class="field-hint">
          This is deliberate. Rather than guess, it tells you when the records do not contain what
          you asked about.
        </p>
      </div>`;
  }

  const sourceCount = result.steps.filter((s) => s.ok).length;
  const rowsRead = result.steps.reduce((sum, s) => sum + (s.row_count || 0), 0);
  const verified = Math.round(result.verification_score * 100);

  const body = result.body
    .split(/\n+/)
    .filter((p) => p.trim())
    .map((p) => `<p>${linkCitations(p)}</p>`)
    .join("");

  const confidence =
    verified >= 90
      ? { kind: "good", text: `Every figure in this answer was checked against your data.` }
      : verified >= 60
        ? { kind: "warn", text: `${verified}% of the figures were confirmed against your data.` }
        : {
            kind: "bad",
            text: `Only ${verified}% could be confirmed. Treat this answer with caution.`,
          };

  const removed = result.removed_claims.length
    ? `<p class="removed-note">
         ${result.removed_claims.length} sentence${result.removed_claims.length === 1 ? " was" : "s were"}
         removed from this answer because the data did not support ${result.removed_claims.length === 1 ? "it" : "them"}.
       </p>`
    : "";

  const sources = result.steps
    .map((step, index) => renderSource(step, index))
    .join("");

  return `
    <article class="panel answer-panel">
      <p class="answer-eyebrow">Answer</p>
      <h2>${escapeHtml(result.title)}</h2>

      <div class="confidence ${confidence.kind}">
        <strong>${verified}% verified</strong>
        <span>${escapeHtml(confidence.text)}</span>
      </div>

      <div class="report-body">${body}</div>
      ${removed}

      ${
        result.limitation
          ? `<p class="limitation">Worth knowing: ${escapeHtml(result.limitation)}</p>`
          : ""
      }

      <p class="answer-howto">
        Each tag like <cite>S1</cite> points to the data behind that number. Click a tag to see it.
      </p>

      <div class="report-actions">
        ${exportActions()}
        <a class="btn btn-ghost btn-sm" href="/app/runs/${encodeURIComponent(result.run_id)}" data-link>Open saved copy</a>
      </div>
    </article>

    <section class="panel">
      <h3 class="panel-title">Where these numbers came from</h3>
      <p class="field-hint">
        It ran <strong>${sourceCount}</strong> search${sourceCount === 1 ? "" : "es"} against your
        records and got <strong>${rowsRead.toLocaleString()}</strong> row${rowsRead === 1 ? "" : "s"}
        back, in ${duration(result.elapsed_ms)}. <strong>Click any row below</strong> to see exactly
        what that search returned.
      </p>
      ${sources}
      <dl class="cost-note">
        <div><dt>Cost</dt><dd><strong>$${result.cost_usd.toFixed(4)}</strong></dd></div>
        <div><dt>AI model</dt><dd>${escapeHtml(result.model)}</dd></div>
        <div><dt>AI work</dt><dd>${result.tokens.toLocaleString()} tokens</dd></div>
      </dl>
    </section>`;
}

const CHEVRON =
  '<svg class="chev" viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" ' +
  'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 2l4 4-4 4"/></svg>';

function renderSource(step, index) {
  if (!step.ok) {
    return `
      <details class="query-card" data-state="${step.refused ? "refused" : "failed"}">
        <summary>
          ${CHEVRON}
          <span class="src">${escapeHtml(step.source_id)}</span>
          <span class="purpose">${escapeHtml(step.purpose)}</span>
          <span class="meta bad">${step.refused ? "blocked for safety" : "did not work"}</span>
        </summary>
        <div class="source-body">
          <p class="refusal-text">${escapeHtml(step.reason)}</p>
        </div>
      </details>`;
  }

  // A search that returned nothing is not a failure, but it must not look like a success
  // either: the answer could not use it, and the reader should be able to see that at a glance.
  const empty = step.row_count === 0;
  return `
    <details class="query-card" data-state="${empty ? "empty" : "ok"}" id="src-${escapeHtml(step.source_id)}"${index === 0 && !empty ? " open" : ""}>
      <summary>
        ${CHEVRON}
        <span class="src">${escapeHtml(step.source_id)}</span>
        <span class="purpose">${escapeHtml(step.purpose)}</span>
        <span class="meta${empty ? " warn" : ""}">
          ${empty ? "nothing found" : `${step.row_count} row${step.row_count === 1 ? "" : "s"}`}
        </span>
        <span class="open-hint">${empty ? "why" : "see the data"}</span>
      </summary>
      <div class="source-body">
        ${
          empty
            ? `<p class="empty-text">
                 This search came back with no rows, so nothing from it was used in the answer.
                 Usually that means the records do not cover what was asked for.
               </p>`
            : `${renderFinding(step)}`
        }
        <details class="raw-query">
          <summary>Show the exact database query</summary>
          <pre class="sql">${escapeHtml(step.executed_sql || step.sql)}</pre>
          <p class="field-hint">
            Checked before it ran. Only reading is permitted, and the connection has no
            permission to change anything.
          </p>
        </details>
      </div>
    </details>`;
}

/* A chart when the shape suits one, then the numbers underneath it. */
function renderFinding(step) {
  const spec = chartSpec(step.columns, step.rows);
  const chart = spec
    ? `<p class="source-label">At a glance</p>${barChart(spec.rows, { legend: spec.legend })}`
    : "";
  return `${chart}<p class="source-label">${spec ? "The exact numbers" : "What it found"}</p>${table(step.columns, step.rows, { limit: 12 })}`;
}

function bindAnswer(stage, result) {
  bindExportActions(stage, { ...result, question: $("#question")?.value || result.question });

  stage.addEventListener("click", (event) => {
    const chip = event.target.closest("cite[data-src]");
    if (!chip) return;
    const target = stage.querySelector(`#src-${CSS.escape(chip.dataset.src)}`);
    if (!target) return;
    target.open = true;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.classList.add("flash");
    setTimeout(() => target.classList.remove("flash"), 900);
  });
}

export function linkCitations(text) {
  return escapeHtml(text).replace(
    /\[S(\d+)\]/g,
    (_, n) => `<cite data-src="S${n}" title="Click to see where this came from">S${n}</cite>`,
  );
}
