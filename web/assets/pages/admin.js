/* Insights, Evaluation and Settings. */

import { auth, data, evaluation, insights, session } from "../api.js";
import { pageHeader } from "../shell.js";
import {
  $,
  barChart,
  duration,
  errorState,
  escapeHtml,
  skeleton,
  sparkline,
  toast,
} from "../ui.js";

export async function insightsPage(view) {
  view.innerHTML = `${pageHeader({ title: "Usage", lede: "How much the team is using Meridian, and how well it is working." })}<div id="body">${skeleton(5)}</div>`;
  let summary;
  try {
    summary = await insights.summary();
  } catch (error) {
    $("#body").innerHTML = errorState(error);
    $("#body").querySelector("[data-retry]")?.addEventListener("click", () => location.reload());
    return;
  }

  const daily = summary.daily || [];
  const counts = daily.map((d) => d.runs);
  const outcomes = Object.entries(summary.by_status || {}).map(([status, count]) => ({
    label: status,
    a: count,
    aLabel: String(count),
  }));

  $("#body").innerHTML = `
    <div class="stat-row">
      ${stat("Questions asked", summary.total_runs.toLocaleString())}
      ${stat("Got an answer", `${Math.round(summary.success_rate * 100)}%`)}
      ${stat("Figures verified", `${Math.round(summary.avg_verification_score * 100)}%`)}
      ${stat("Cost per question", `$${summary.avg_cost_usd.toFixed(4)}`)}
      ${stat("Typical wait", duration(summary.p50_duration_seconds * 1000))}
      ${stat("Slowest one in twenty", duration(summary.p95_duration_seconds * 1000))}
    </div>

    <section class="panel">
      <h3 class="panel-title">Questions asked per day</h3>
      ${counts.length ? sparkline(counts, { width: 600, height: 70 }) : '<p class="muted">Nobody has asked anything yet.</p>'}
      <div class="day-axis">
        ${daily.length ? `<span>${escapeHtml(daily[0].day)}</span><span>${escapeHtml(daily[daily.length - 1].day)}</span>` : ""}
      </div>
    </section>

    <div class="two-col">
      <section class="panel">
        <h3 class="panel-title">How they ended</h3>
        ${barChart(outcomes, { legend: [], format: (v) => String(v) })}
      </section>
      <section class="panel">
        <h3 class="panel-title">Detail</h3>
        <dl class="kv">
          <div><dt>Average searches per question</dt><dd>${summary.avg_steps}</dd></div>
          <div><dt>Stopped at the spending limit</dt><dd>${Math.round(summary.budget_exhausted_rate * 100)}%</dd></div>
          <div><dt>Answered</dt><dd>${summary.completed}</dd></div>
          <div><dt>No answer found</dt><dd>${summary.failed}</dd></div>
        </dl>
        <p class="field-hint">
          "Slowest one in twenty" matters more than the average, because it is the wait
          people actually complain about.
        </p>
      </section>
    </div>`;
}

function stat(label, value) {
  return `<div class="stat"><span class="stat-label">${escapeHtml(label)}</span><strong class="stat-value">${escapeHtml(value)}</strong></div>`;
}

const CATEGORY_BLURB = {
  "SQL guard":
    "Attempts to damage, delete or read data the assistant should never touch - plus ordinary " +
    "queries that must still be allowed through.",
  "Prompt injection":
    "Text hidden inside documents trying to give the assistant orders - plus ordinary memos " +
    "that must not be mistaken for an attack.",
};

const PLAIN = { refuse: "blocked", flag: "flagged", allow: "allowed", pass_through: "allowed" };

export async function evaluationPage(view) {
  view.innerHTML = `${pageHeader({
    title: "Safety checks",
    lede: "Every protection, tested for real each time you open this page. None of this is a stored result.",
  })}<div id="body">${skeleton(6)}</div>`;

  let suite;
  try {
    suite = await evaluation.suite();
  } catch (error) {
    $("#body").innerHTML = errorState(error);
    $("#body").querySelector("[data-retry]")?.addEventListener("click", () => location.reload());
    return;
  }

  const summary = suite.summary;
  const categories = [...new Set(suite.results.map((r) => r.category))];

  $("#body").innerHTML = `
    <div class="stat-row">
      ${stat("Checks passed", `${summary.passed}/${summary.total}`)}
      ${stat("Pass rate", `${Math.round(summary.pass_rate * 100)}%`)}
      ${stat("Attacks blocked", `${summary.attacks_blocked}/${summary.attacks_total}`)}
      ${stat("Normal work allowed", `${summary.benign_allowed}/${summary.benign_total}`)}
    </div>

    <section class="panel">
      <p class="field-hint">
        Two numbers, not one. Letting an attack through leaves a hole. Blocking ordinary work
        is just as damaging in practice, because people switch the protection off. Something
        that refused everything would score perfectly on the first number and be useless.
      </p>
    </section>

    ${categories
      .map((category) => {
        const rows = suite.results.filter((r) => r.category === category);
        return `
        <section class="panel">
          <h3 class="panel-title">${escapeHtml(category)}</h3>
          <p class="field-hint">${escapeHtml(CATEGORY_BLURB[category] || "")}</p>
          <div class="scenario-list">
            ${rows
              .map(
                (r) => `
              <details class="scenario ${r.passed ? "pass" : "fail"}">
                <summary>
                  <span class="verdict">${r.passed ? "✓" : "✗"}</span>
                  <span class="scenario-name">${escapeHtml(r.name)}</span>
                  <span class="scenario-expect">should be ${escapeHtml(PLAIN[r.expectation] || r.expectation)} · was ${escapeHtml(r.observed)}</span>
                </summary>
                <p class="scenario-why"><strong>Why this matters:</strong> ${escapeHtml(r.rationale)}</p>
                <p class="scenario-result ${r.passed ? "pass" : "fail"}">
                  <strong>${r.passed ? "Handled correctly." : "Not handled."}</strong>
                  ${escapeHtml(r.detail)}
                </p>
                <details class="raw-query">
                  <summary>Show what was actually sent</summary>
                  <pre class="sql">${escapeHtml(r.payload)}</pre>
                </details>
              </details>`,
              )
              .join("")}
          </div>
        </section>`;
      })
      .join("")}`;
}

export async function settingsPage(view) {
  const user = session.user;
  const isAdmin = user?.role === "admin";

  view.innerHTML = `
    ${pageHeader({ title: "Settings", lede: "Your account, and how this copy of Meridian is set up." })}
    <div class="two-col">
      <section class="panel">
        <h3 class="panel-title">Your account</h3>
        <dl class="kv">
          <div><dt>Name</dt><dd>${escapeHtml(user?.display_name || "")}</dd></div>
          <div><dt>Email</dt><dd>${escapeHtml(user?.email || "")}</dd></div>
          <div><dt>Role</dt><dd>${escapeHtml(user?.role || "")}</dd></div>
          <div><dt>Type</dt><dd>${user?.is_demo ? "Demo account" : "Standard account"}</dd></div>
        </dl>
        <p class="field-hint">
          What the roles mean: a viewer can read answers but not ask new questions, an analyst
          can ask questions, and an admin can also see Usage and change who has which role.
        </p>
      </section>
      <section class="panel">
        <h3 class="panel-title">How this copy is set up</h3>
        <div id="providers">${skeleton(3)}</div>
      </section>
    </div>
    ${isAdmin ? '<section class="panel"><h3 class="panel-title">People with access</h3><div id="users">' + skeleton(3) + "</div></section>" : ""}`;

  try {
    const providers = await data.providers();
    $("#providers").innerHTML = `
      <dl class="kv">
        <div><dt>AI model</dt><dd><code>${escapeHtml(providers.model)}</code></dd></div>
        <div><dt>Where it runs</dt><dd>${providers.scripted ? "Built in, no internet" : "External AI service"}</dd></div>
        <div><dt>Document search</dt><dd><code>${escapeHtml(providers.embedding_provider)}</code></dd></div>
        <div><dt>Outside sources</dt><dd><code>${escapeHtml(providers.tools_mode)}</code></dd></div>
        <div><dt>Job handling</dt><dd><code>${escapeHtml(providers.queue)}</code></dd></div>
      </dl>
      <p class="field-hint">
        ${providers.fully_offline
          ? "Nothing leaves this machine. No internet connection is made at any point."
          : "Your questions go to the AI service named above, and nowhere else."}
      </p>`;
  } catch (error) {
    $("#providers").innerHTML = errorState(error);
  }

  if (!isAdmin) return;

  async function loadUsers() {
    try {
      const users = await auth.listUsers();
      $("#users").innerHTML = `
        <table class="health-table">
          <thead><tr><th>Name</th><th>Email</th><th>Can do</th><th>Change</th></tr></thead>
          <tbody>
            ${users
              .map(
                (u) => `
              <tr>
                <td>${escapeHtml(u.display_name)}</td>
                <td class="muted">${escapeHtml(u.email)}</td>
                <td><span class="badge badge-${u.role === "admin" ? "good" : "warn"}">${escapeHtml(u.role)}</span></td>
                <td>
                  <select data-user="${escapeHtml(u.id)}" aria-label="Role for ${escapeHtml(u.display_name)}">
                    ${["viewer", "analyst", "admin"]
                      .map((r) => `<option value="${r}"${r === u.role ? " selected" : ""}>${r}</option>`)
                      .join("")}
                  </select>
                </td>
              </tr>`,
              )
              .join("")}
          </tbody>
        </table>`;

      $("#users").addEventListener("change", async (event) => {
        const select = event.target.closest("[data-user]");
        if (!select) return;
        try {
          await auth.setRole(select.dataset.user, select.value);
          toast("Updated. They will see the change next time they sign in.", "success");
          loadUsers();
        } catch (error) {
          toast(error.message, "error");
          loadUsers();
        }
      });
    } catch (error) {
      $("#users").innerHTML = errorState(error);
    }
  }
  await loadUsers();
}
