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
  view.innerHTML = `${pageHeader({ title: "Insights", lede: "Activity across every user's runs." })}<div id="body">${skeleton(5)}</div>`;
  let summary;
  try {
    summary = await insights.summary();
  } catch (error) {
    $("#body").innerHTML = errorState(error);
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
      ${stat("Total runs", summary.total_runs.toLocaleString())}
      ${stat("Success rate", `${Math.round(summary.success_rate * 100)}%`)}
      ${stat("Avg verification", `${Math.round(summary.avg_verification_score * 100)}%`)}
      ${stat("Avg cost", `$${summary.avg_cost_usd.toFixed(4)}`)}
      ${stat("p50 duration", duration(summary.p50_duration_seconds * 1000))}
      ${stat("p95 duration", duration(summary.p95_duration_seconds * 1000))}
    </div>

    <section class="panel">
      <h3 class="panel-title">Runs per day</h3>
      ${counts.length ? sparkline(counts, { width: 600, height: 70 }) : '<p class="muted">No history yet.</p>'}
      <div class="day-axis">
        ${daily.length ? `<span>${escapeHtml(daily[0].day)}</span><span>${escapeHtml(daily[daily.length - 1].day)}</span>` : ""}
      </div>
    </section>

    <div class="two-col">
      <section class="panel">
        <h3 class="panel-title">Outcomes</h3>
        ${barChart(outcomes, { legend: [], format: (v) => String(v) })}
      </section>
      <section class="panel">
        <h3 class="panel-title">Budget and steps</h3>
        <dl class="kv">
          <div><dt>Average steps per run</dt><dd>${summary.avg_steps}</dd></div>
          <div><dt>Budget exhausted</dt><dd>${Math.round(summary.budget_exhausted_rate * 100)}%</dd></div>
          <div><dt>Completed</dt><dd>${summary.completed}</dd></div>
          <div><dt>Failed</dt><dd>${summary.failed}</dd></div>
        </dl>
        <p class="field-hint">
          Percentiles use the nearest-rank method. With a few dozen runs, interpolating between
          samples would invent precision the data does not support.
        </p>
      </section>
    </div>`;
}

function stat(label, value) {
  return `<div class="stat"><span class="stat-label">${escapeHtml(label)}</span><strong class="stat-value">${escapeHtml(value)}</strong></div>`;
}

export async function evaluationPage(view) {
  view.innerHTML = `${pageHeader({
    title: "Evaluation",
    lede: "The security suite, executed against the real guards each time this page loads.",
  })}<div id="body">${skeleton(6)}</div>`;

  let suite;
  try {
    suite = await evaluation.suite();
  } catch (error) {
    $("#body").innerHTML = errorState(error);
    return;
  }

  const summary = suite.summary;
  const categories = [...new Set(suite.results.map((r) => r.category))];

  $("#body").innerHTML = `
    <div class="stat-row">
      ${stat("Scenarios", `${summary.passed}/${summary.total}`)}
      ${stat("Pass rate", `${Math.round(summary.pass_rate * 100)}%`)}
      ${stat("Attacks blocked", `${summary.attacks_blocked}/${summary.attacks_total}`)}
      ${stat("Benign allowed", `${summary.benign_allowed}/${summary.benign_total}`)}
    </div>

    <section class="panel">
      <p class="field-hint">
        Two numbers, not one. A missed attack is a hole; a blocked legitimate query is friction.
        A guard that refuses everything scores perfectly on the first and fails the product.
      </p>
    </section>

    ${categories
      .map((category) => {
        const rows = suite.results.filter((r) => r.category === category);
        return `
        <section class="panel">
          <h3 class="panel-title">${escapeHtml(category)}</h3>
          <div class="scenario-list">
            ${rows
              .map(
                (r) => `
              <details class="scenario ${r.passed ? "pass" : "fail"}">
                <summary>
                  <span class="verdict">${r.passed ? "✓" : "✗"}</span>
                  <span class="scenario-name">${escapeHtml(r.name)}</span>
                  <span class="scenario-expect">expected ${escapeHtml(r.expectation)} · got ${escapeHtml(r.observed)}</span>
                </summary>
                <p class="field-hint">${escapeHtml(r.rationale)}</p>
                <pre class="sql">${escapeHtml(r.payload)}</pre>
                <p class="muted">${escapeHtml(r.detail)}</p>
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
    ${pageHeader({ title: "Settings", lede: "Your profile and what this deployment is running." })}
    <div class="two-col">
      <section class="panel">
        <h3 class="panel-title">Profile</h3>
        <dl class="kv">
          <div><dt>Name</dt><dd>${escapeHtml(user?.display_name || "")}</dd></div>
          <div><dt>Email</dt><dd>${escapeHtml(user?.email || "")}</dd></div>
          <div><dt>Role</dt><dd>${escapeHtml(user?.role || "")}</dd></div>
          <div><dt>Account type</dt><dd>${user?.is_demo ? "Demo account" : "Standard"}</dd></div>
        </dl>
        <p class="field-hint">
          Roles: a viewer reads research, an analyst starts runs, an admin also sees Insights and
          manages users.
        </p>
      </section>
      <section class="panel">
        <h3 class="panel-title">Model and tools</h3>
        <div id="providers">${skeleton(3)}</div>
      </section>
    </div>
    ${isAdmin ? '<section class="panel"><h3 class="panel-title">Users</h3><div id="users">' + skeleton(3) + "</div></section>" : ""}`;

  try {
    const providers = await data.providers();
    $("#providers").innerHTML = `
      <dl class="kv">
        <div><dt>Model</dt><dd><code>${escapeHtml(providers.model)}</code></dd></div>
        <div><dt>Provider</dt><dd>${providers.scripted ? "built-in scripted" : "OpenAI-compatible"}</dd></div>
        <div><dt>Embeddings</dt><dd><code>${escapeHtml(providers.embedding_provider)}</code></dd></div>
        <div><dt>External tools</dt><dd><code>${escapeHtml(providers.tools_mode)}</code></dd></div>
        <div><dt>Queue</dt><dd><code>${escapeHtml(providers.queue)}</code></dd></div>
      </dl>
      <p class="field-hint">
        ${providers.fully_offline
          ? "Fully offline: no outbound network calls."
          : "Outbound calls go to the configured model provider only."}
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
          <thead><tr><th>Name</th><th>Email</th><th>Role</th><th></th></tr></thead>
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
          toast("Role updated.", "success");
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
