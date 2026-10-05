/* Sign in, sign up, and the one-click demo accounts. */

import { auth } from "../api.js";
import { navigate } from "../shell.js";
import { $, escapeHtml, toast } from "../ui.js";

const DEMO_ACCOUNTS = [
  {
    role: "admin",
    name: "Dana Admin",
    detail: "Everything, plus Insights and user management",
  },
  { role: "analyst", name: "Avery Analyst", detail: "Start runs and read every report" },
  { role: "viewer", name: "Robin Viewer", detail: "Read-only: can open reports, cannot run" },
];

export async function signInPage(root) {
  root.innerHTML = `
    <div class="auth-page">
      <a class="brand" href="/" data-link>
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-name">Meridian</span>
      </a>

      <div class="auth-card">
        <h1>Sign in</h1>
        <p class="muted">Pick a demo account, or use an email and password.</p>

        <div class="demo-grid">
          ${DEMO_ACCOUNTS.map(
            (account) => `
            <button class="demo-card" type="button" data-role="${account.role}">
              <strong>${escapeHtml(account.name)}</strong>
              <span class="badge badge-${account.role === "admin" ? "good" : account.role === "analyst" ? "warn" : "bad"}">${escapeHtml(account.role)}</span>
              <em>${escapeHtml(account.detail)}</em>
            </button>`,
          ).join("")}
        </div>

        <div class="divider"><span>or</span></div>

        <form id="credentials" novalidate>
          <label class="field-label" for="email">Email</label>
          <input id="email" type="email" autocomplete="username" placeholder="analyst@meridian.demo" />
          <label class="field-label" for="password">Password</label>
          <input id="password" type="password" autocomplete="current-password" placeholder="demo-password" />
          <div class="auth-actions">
            <button class="btn btn-primary" type="submit" id="submit">Sign in</button>
            <button class="btn btn-ghost" type="button" id="create">Create an account</button>
          </div>
          <p class="auth-error" id="error" hidden></p>
        </form>

        <p class="field-hint">
          Demo accounts all use the password <code>demo-password</code>. They are seeded by
          <code>tasks.ps1 seed</code> and flagged in the database, so this route can never reach a
          real account.
        </p>
      </div>
    </div>`;

  const afterSignIn = () => {
    const target = sessionStorage.getItem("meridian.returnTo") || "/app/new";
    sessionStorage.removeItem("meridian.returnTo");
    navigate(target);
  };

  root.querySelector(".demo-grid").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-role]");
    if (!button) return;
    button.disabled = true;
    try {
      const user = await auth.demo(button.dataset.role);
      toast(`Signed in as ${user.display_name}.`, "success");
      afterSignIn();
    } catch (error) {
      showError(error.message);
      button.disabled = false;
    }
  });

  $("#credentials").addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = $("#email").value.trim();
    const password = $("#password").value;
    if (!email || !password) {
      showError("Enter both an email and a password.");
      return;
    }
    $("#submit").disabled = true;
    try {
      const user = await auth.login(email, password);
      toast(`Welcome back, ${user.display_name}.`, "success");
      afterSignIn();
    } catch (error) {
      showError(error.message);
    } finally {
      $("#submit").disabled = false;
    }
  });

  $("#create").addEventListener("click", async () => {
    const email = $("#email").value.trim();
    const password = $("#password").value;
    if (!email || password.length < 8) {
      showError("To create an account, enter an email and a password of at least 8 characters.");
      return;
    }
    try {
      const user = await auth.signup(email, password, email.split("@")[0]);
      toast(`Account created for ${user.display_name}.`, "success");
      afterSignIn();
    } catch (error) {
      showError(error.message);
    }
  });

  function showError(message) {
    const node = $("#error");
    node.textContent = message;
    node.hidden = false;
  }
}
