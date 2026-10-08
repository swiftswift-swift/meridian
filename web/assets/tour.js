/* A four-step tour on first arrival.

   It points at real elements rather than showing screenshots, so it cannot go stale when the
   layout changes: if a target is missing the step is skipped instead of highlighting empty
   space. Dismissal is remembered, and it can be replayed from Settings. */

import { $, escapeHtml } from "./ui.js";

const SEEN_KEY = "meridian.tourDone";

const STEPS = [
  {
    target: "#question",
    title: "Ask in plain English",
    body: "Type a question the way you would ask a colleague. No menus to learn, no query language.",
    place: "below",
  },
  {
    target: "#examples",
    title: "Or start from an example",
    body: "Nine questions that all work, grouped by what you are trying to find out. Click one and it runs.",
    place: "above",
  },
  {
    target: ".side-link[href='/app/data']",
    title: "See what it can reach",
    body: "The records and documents it is allowed to read, plus a page where you can try to make it do damage and watch it refuse.",
    place: "right",
  },
  {
    target: ".side-link[href='/app/runs']",
    title: "Nothing is lost",
    body: "Every answer is saved with the data behind it, so you can reopen it months later or send someone a link.",
    place: "right",
  },
];

let index = 0;
let active = [];

export function tourDone() {
  return localStorage.getItem(SEEN_KEY) === "1";
}

export function startTour({ force = false } = {}) {
  if (!force && tourDone()) return;
  active = STEPS.filter((step) => document.querySelector(step.target));
  if (!active.length) return;
  index = 0;
  paint();
}

function finish() {
  localStorage.setItem(SEEN_KEY, "1");
  $("#tour")?.remove();
  document.querySelector(".tour-target")?.classList.remove("tour-target");
}

function paint() {
  $("#tour")?.remove();
  document.querySelector(".tour-target")?.classList.remove("tour-target");

  const step = active[index];
  const target = document.querySelector(step.target);
  if (!target) {
    finish();
    return;
  }
  target.classList.add("tour-target");
  target.scrollIntoView({ block: "center", behavior: "smooth" });

  const host = document.createElement("div");
  host.id = "tour";
  host.className = "tour-backdrop";
  host.innerHTML = `
    <div class="tour-card" role="dialog" aria-modal="true" aria-label="Guided tour">
      <p class="tour-step">Step ${index + 1} of ${active.length}</p>
      <h3>${escapeHtml(step.title)}</h3>
      <p>${escapeHtml(step.body)}</p>
      <div class="tour-actions">
        <button class="btn btn-ghost btn-sm" data-tour="skip">Skip</button>
        <div class="tour-right">
          ${index > 0 ? '<button class="btn btn-ghost btn-sm" data-tour="back">Back</button>' : ""}
          <button class="btn btn-primary btn-sm" data-tour="next">
            ${index === active.length - 1 ? "Done" : "Next"}
          </button>
        </div>
      </div>
    </div>`;
  document.body.append(host);

  // Positioned after insertion, because the card's size is not known until it is in the DOM.
  position(host.querySelector(".tour-card"), target, step.place);

  host.addEventListener("click", (event) => {
    const action = event.target.closest("[data-tour]")?.dataset.tour;
    if (!action) return;
    if (action === "skip") finish();
    else if (action === "back") {
      index -= 1;
      paint();
    } else if (index === active.length - 1) finish();
    else {
      index += 1;
      paint();
    }
  });
}

function position(card, target, place) {
  const box = target.getBoundingClientRect();
  const gap = 14;
  const width = card.offsetWidth;
  const height = card.offsetHeight;

  let top = box.bottom + gap;
  let left = box.left;

  if (place === "above") top = box.top - height - gap;
  if (place === "right") {
    top = box.top;
    left = box.right + gap;
  }

  // Keep the card on screen whatever the target's position.
  left = Math.min(Math.max(12, left), window.innerWidth - width - 12);
  top = Math.min(Math.max(12, top), window.innerHeight - height - 12);

  card.style.top = `${top}px`;
  card.style.left = `${left}px`;
}
