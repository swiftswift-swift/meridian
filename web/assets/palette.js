/* The command palette: Ctrl+K from anywhere.

   Worth the code because it collapses the whole product into one keystroke, and because a
   keyboard user can reach every page without tabbing through a sidebar. Entries are built from
   the same route table the navigation uses, so a new page appears here automatically. */

import { session } from "./api.js";
import { navigate } from "./shell.js";
import { $, escapeHtml } from "./ui.js";

const PAGES = [
  { label: "Ask a question", hint: "Start a new investigation", href: "/app/new", keys: "ask new question" },
  { label: "Past answers", hint: "Everything asked before", href: "/app/runs", keys: "history runs past" },
  { label: "What it can see", hint: "Records, documents and the safety demo", href: "/app/data", keys: "data sources schema documents" },
  { label: "Usage", hint: "Team activity and cost", href: "/app/insights", keys: "insights metrics usage cost", admin: true },
  { label: "Safety checks", hint: "Every protection, tested live", href: "/app/evaluation", keys: "safety security evaluation" },
  { label: "Settings", hint: "Your account and how this is set up", href: "/app/settings", keys: "settings profile account" },
];

const QUESTIONS = [
  "Why did EMEA revenue drop in Q3 compared to Q2?",
  "Which product line should we prioritise next quarter?",
  "Is any marketing campaign wasting money?",
  "Which customer has the highest lifetime revenue?",
  "Which country generates the most revenue?",
];

let open = false;
let cursor = 0;
let entries = [];

export function initPalette() {
  document.addEventListener("keydown", (event) => {
    const combo = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
    if (combo) {
      event.preventDefault();
      toggle();
      return;
    }
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(entries[cursor]);
    }
  });
}

function toggle() {
  if (open) close();
  else show();
}

function show() {
  if (!session.token) return;
  open = true;
  cursor = 0;

  const host = document.createElement("div");
  host.className = "palette-backdrop";
  host.id = "palette";
  host.innerHTML = `
    <div class="palette" role="dialog" aria-modal="true" aria-label="Command palette">
      <input id="palette-input" type="text" autocomplete="off" spellcheck="false"
        placeholder="Jump to a page, or type a question to ask" aria-label="Search" />
      <ul class="palette-list" id="palette-list"></ul>
      <footer class="palette-foot">
        <span><kbd>&uarr;</kbd><kbd>&darr;</kbd> move</span>
        <span><kbd>Enter</kbd> select</span>
        <span><kbd>Esc</kbd> close</span>
      </footer>
    </div>`;
  document.body.append(host);
  host.addEventListener("click", (event) => {
    if (event.target === host) close();
  });

  const input = $("#palette-input");
  input.addEventListener("input", () => render(input.value));
  $("#palette-list").addEventListener("click", (event) => {
    const item = event.target.closest("[data-index]");
    if (item) choose(entries[Number(item.dataset.index)]);
  });
  render("");
  input.focus();
}

function close() {
  open = false;
  $("#palette")?.remove();
}

function move(delta) {
  if (!entries.length) return;
  cursor = (cursor + delta + entries.length) % entries.length;
  paint();
  $(`[data-index="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
}

function choose(entry) {
  if (!entry) return;
  close();
  entry.run();
}

function render(query) {
  const needle = query.trim().toLowerCase();
  const isAdmin = session.user?.role === "admin";

  const pages = PAGES.filter((page) => !page.admin || isAdmin)
    .filter((page) => !needle || `${page.label} ${page.keys}`.toLowerCase().includes(needle))
    .map((page) => ({
      group: "Go to",
      label: page.label,
      hint: page.hint,
      run: () => navigate(page.href),
    }));

  const matching = QUESTIONS.filter(
    (question) => !needle || question.toLowerCase().includes(needle),
  ).map((question) => ({
    group: "Ask",
    label: question,
    hint: "Run this question",
    run: () => ask(question),
  }));

  // Anything typed that is not a page name is treated as a question, so the palette doubles as
  // the fastest way to start a run from any page.
  const freeform =
    needle.length > 8 && !matching.some((m) => m.label.toLowerCase() === needle)
      ? [
          {
            group: "Ask",
            label: query.trim(),
            hint: "Ask this as a new question",
            run: () => ask(query.trim()),
          },
        ]
      : [];

  entries = [...freeform, ...pages, ...matching];
  cursor = 0;
  paint();
}

function ask(question) {
  sessionStorage.setItem("meridian.prefill", question);
  sessionStorage.setItem("meridian.autorun", "1");
  navigate("/app/new");
}

function paint() {
  const list = $("#palette-list");
  if (!list) return;
  if (!entries.length) {
    list.innerHTML = '<li class="palette-empty">Nothing matches. Press Esc to close.</li>';
    return;
  }
  let lastGroup = null;
  list.innerHTML = entries
    .map((entry, index) => {
      const heading =
        entry.group === lastGroup ? "" : `<li class="palette-group">${escapeHtml(entry.group)}</li>`;
      lastGroup = entry.group;
      return `${heading}
        <li class="palette-item${index === cursor ? " active" : ""}" data-index="${index}">
          <span class="palette-label">${escapeHtml(entry.label)}</span>
          <span class="palette-hint">${escapeHtml(entry.hint)}</span>
        </li>`;
    })
    .join("");
}
