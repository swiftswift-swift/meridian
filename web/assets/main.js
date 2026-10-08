/* Application entry point: wire the routes, restore the session, render.

   ES modules served directly, no bundler. The React and Vite phase in PLAN.md would replace this
   file and its pages; the API client and the server contract would not change. */

import { auth, session } from "./api.js";
import { initLinks, initTheme, navigate, render, route, setNotFound } from "./shell.js";
import { landingPage } from "./pages/landing.js";
import { signInPage } from "./pages/signin.js";
import { researchPage } from "./pages/research.js";
import { runDetailPage, runsPage } from "./pages/runs.js";
import { dataPage } from "./pages/data.js";
import { evaluationPage, insightsPage, settingsPage } from "./pages/admin.js";
import { sharedReportPage } from "./pages/shared.js";
import { initPalette } from "./palette.js";
import { escapeHtml } from "./ui.js";

route("/", landingPage);
route("/signin", signInPage);
route("/shared/:token", sharedReportPage);

route("/app", async () => navigate("/app/new", { replace: true }), { auth: true });
route("/app/new", researchPage, { auth: true, shell: true, nav: "new" });
route("/app/runs", runsPage, { auth: true, shell: true, nav: "runs" });
route("/app/runs/:id", runDetailPage, { auth: true, shell: true, nav: "runs" });
route("/app/data", dataPage, { auth: true, shell: true, nav: "data" });
route("/app/insights", insightsPage, { auth: true, shell: true, nav: "insights" });
route("/app/evaluation", evaluationPage, { auth: true, shell: true, nav: "evaluation" });
route("/app/settings", settingsPage, { auth: true, shell: true, nav: "settings" });

setNotFound(
  () => `
  <div class="auth-page">
    <div class="auth-card">
      <h1>Page not found</h1>
      <p class="muted">${escapeHtml(location.pathname)} does not exist.</p>
      <a class="btn btn-primary" href="/" data-link>Back to the start</a>
    </div>
  </div>`,
);

async function boot() {
  initTheme();
  initLinks();
  initPalette();
  // Restore the session before the first render so a refresh inside the workspace does not
  // bounce the user out to sign-in and back.
  if (session.token) {
    try {
      await auth.me();
    } catch {
      session.token = null;
    }
  }
  await render();
}

boot();
