/* The workspace shell: sidebar, user menu, theme, mobile drawer, and the router.

   Routing is history-based rather than hash-based because FastAPI already serves index.html for
   any unmatched path, so a deep link survives a reload. */

import { auth, session } from "./api.js";
import { $, $$, escapeHtml, toast } from "./ui.js";

const routes = [];
let notFound = null;
let currentCleanup = null;

export function route(pattern, handler, options = {}) {
  // "/app/runs/:id" becomes a regex with a named group so the handler gets {id}.
  const names = [];
  const source = pattern
    .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
    .replace(/:(\w+)/g, (_, name) => {
      names.push(name);
      return "([^/]+)";
    });
  routes.push({ regex: new RegExp(`^${source}/?$`), names, handler, options });
}

export function setNotFound(handler) {
  notFound = handler;
}

export function navigate(path, { replace = false } = {}) {
  if (replace) history.replaceState({}, "", path);
  else history.pushState({}, "", path);
  render();
}

export async function render() {
  const path = location.pathname;
  const match = routes
    .map((candidate) => ({ candidate, found: candidate.regex.exec(path) }))
    .find((entry) => entry.found);

  if (typeof currentCleanup === "function") {
    currentCleanup();
    currentCleanup = null;
  }

  if (!match) {
    document.body.dataset.shell = "none";
    $("#root").innerHTML = notFound ? notFound() : "<p>Not found.</p>";
    return;
  }

  const { candidate, found } = match;
  const params = {};
  candidate.names.forEach((name, index) => {
    params[name] = decodeURIComponent(found[index + 1]);
  });

  if (candidate.options.auth && !session.token) {
    // Remember where they were going so sign-in can return them to it.
    sessionStorage.setItem("meridian.returnTo", path);
    navigate("/signin", { replace: true });
    return;
  }

  if (candidate.options.auth && !session.user) {
    try {
      await auth.me();
    } catch {
      session.token = null;
      sessionStorage.setItem("meridian.returnTo", path);
      navigate("/signin", { replace: true });
      return;
    }
  }

  document.body.dataset.shell = candidate.options.shell ? "workspace" : "public";
  if (candidate.options.shell) {
    renderShell(candidate.options.nav);
    currentCleanup = await candidate.handler($("#view"), params);
  } else {
    $("#root").innerHTML = "";
    currentCleanup = await candidate.handler($("#root"), params);
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}

const NAV = [
  { href: "/app/new", label: "Ask a question", icon: "search", key: "new" },
  { href: "/app/runs", label: "Past answers", icon: "list", key: "runs" },
  { href: "/app/data", label: "What it can see", icon: "database", key: "data" },
  { href: "/app/insights", label: "Usage", icon: "chart", key: "insights", admin: true },
  { href: "/app/evaluation", label: "Safety checks", icon: "shield", key: "evaluation" },
  { href: "/app/settings", label: "Settings", icon: "cog", key: "settings" },
];

const ICONS = {
  search:
    '<circle cx="7" cy="7" r="5"/><path d="M11 11l4 4"/>',
  list: '<path d="M3 4h12M3 9h12M3 14h8"/>',
  database:
    '<ellipse cx="9" cy="4.5" rx="6" ry="2.5"/><path d="M3 4.5v9c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-9"/><path d="M3 9c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5"/>',
  chart: '<path d="M3 15V9M8 15V4M13 15v-4"/>',
  shield: '<path d="M9 2l6 2.5v4C15 12 12.5 15 9 16.5 5.5 15 3 12 3 8.5v-4z"/>',
  cog: '<circle cx="9" cy="9" r="2.5"/><path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.8 3.8l1.4 1.4M12.8 12.8l1.4 1.4M14.2 3.8l-1.4 1.4M5.2 12.8l-1.4 1.4"/>',
};

function icon(name) {
  return `<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}

function renderShell(activeKey) {
  const root = $("#root");
  const isAdmin = session.user?.role === "admin";

  if (root.dataset.shellRendered !== "true") {
    root.innerHTML = `
      <div class="workspace">
        <button class="drawer-toggle" id="drawer-toggle" aria-label="Open navigation" aria-expanded="false">
          <span></span><span></span><span></span>
        </button>
        <aside class="sidebar" id="sidebar">
          <a class="brand" href="/" data-link>
            <span class="brand-mark" aria-hidden="true"></span>
            <span class="brand-name">Meridian</span>
          </a>
          <nav class="side-nav" id="side-nav" aria-label="Workspace"></nav>
          <div class="side-foot">
            <button class="theme-btn" id="theme-toggle" type="button">
              <span data-theme-icon>Light</span>
            </button>
            <div class="user-chip" id="user-chip"></div>
          </div>
        </aside>
        <div class="scrim" id="scrim" hidden></div>
        <main class="view" id="view"></main>
      </div>`;
    root.dataset.shellRendered = "true";

    $("#drawer-toggle").addEventListener("click", () => {
      const open = document.body.classList.toggle("drawer-open");
      $("#drawer-toggle").setAttribute("aria-expanded", String(open));
      $("#scrim").hidden = !open;
    });
    $("#scrim").addEventListener("click", closeDrawer);
    $("#theme-toggle").addEventListener("click", toggleTheme);
  }

  $("#side-nav").innerHTML = NAV.filter((item) => !item.admin || isAdmin)
    .map(
      (item) => `
      <a href="${item.href}" data-link class="side-link${item.key === activeKey ? " active" : ""}">
        ${icon(item.icon)}<span>${escapeHtml(item.label)}</span>
      </a>`,
    )
    .join("");

  const user = session.user;
  $("#user-chip").innerHTML = user
    ? `
      <div class="avatar" aria-hidden="true">${escapeHtml((user.display_name || "?").slice(0, 1))}</div>
      <div class="user-meta">
        <strong>${escapeHtml(user.display_name)}</strong>
        <span>${escapeHtml(user.role)}</span>
      </div>
      <button class="btn btn-ghost btn-sm" id="sign-out" type="button">Sign out</button>`
    : "";
  const signOut = $("#sign-out");
  if (signOut) {
    signOut.addEventListener("click", () => {
      auth.signOut();
      toast("Signed out.", "info");
      navigate("/");
    });
  }
  applyThemeIcon();
}

function closeDrawer() {
  document.body.classList.remove("drawer-open");
  const toggle = $("#drawer-toggle");
  if (toggle) toggle.setAttribute("aria-expanded", "false");
  const scrim = $("#scrim");
  if (scrim) scrim.hidden = true;
}

export function initTheme() {
  const stored = localStorage.getItem("meridian.theme");
  const prefersLight = window.matchMedia("(prefers-color-scheme: light)").matches;
  document.documentElement.dataset.theme = stored || (prefersLight ? "light" : "dark");
  applyThemeIcon();
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("meridian.theme", next);
  applyThemeIcon();
}

function applyThemeIcon() {
  const label = document.documentElement.dataset.theme === "dark" ? "Light" : "Dark";
  $$("[data-theme-icon]").forEach((node) => {
    node.textContent = label;
  });
}

export function initLinks() {
  // One delegated listener for every internal link, present and future.
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-link]");
    if (!link) return;
    const url = new URL(link.href, location.origin);
    if (url.origin !== location.origin) return;
    event.preventDefault();
    closeDrawer();
    navigate(url.pathname + url.search);
  });
  window.addEventListener("popstate", render);
}

export function pageHeader({ title, lede, actions = "" }) {
  return `
    <header class="page-head">
      <div>
        <h1>${escapeHtml(title)}</h1>
        ${lede ? `<p class="page-lede">${escapeHtml(lede)}</p>` : ""}
      </div>
      ${actions ? `<div class="page-actions">${actions}</div>` : ""}
    </header>`;
}
