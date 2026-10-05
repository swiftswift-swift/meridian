/* The public landing page. */

import { session } from "../api.js";
import { navigate } from "../shell.js";
import { $, escapeHtml } from "../ui.js";

const STEPS = [
  {
    n: 1,
    title: "It makes a plan",
    body: "The model is given the database schema and the period the data covers, and asked for concrete steps plus the SQL for each one.",
    state: "built",
    tag: "built",
  },
  {
    n: 2,
    title: "You approve the plan",
    body: "It stops and waits. You approve, reword the steps, or cancel. Nothing is spent and nothing runs until you say so.",
    state: "partial",
    tag: "on the built-in questions only",
  },
  {
    n: 3,
    title: "It does the work",
    body: "Each query it wrote is checked by the guard, then run against a read-only connection. A refused query is reported, not silently dropped.",
    state: "built",
    tag: "built",
  },
  {
    n: 4,
    title: "It changes course if needed",
    body: "Re-planning when the evidence contradicts the plan. Today it runs a single pass: plan, query, write.",
    state: "no",
    tag: "designed, not built",
  },
  {
    n: 5,
    title: "It checks its own homework",
    body: "Every number in the answer is matched against the rows that came back. Unsupported sentences are deleted and the score drops. No model is involved: this is a pure function.",
    state: "built",
    tag: "built",
  },
  {
    n: 6,
    title: "It survives a crash",
    body: "Resuming from the last checkpoint without repeating work. The ledger table and its uniqueness constraint exist; the worker that uses them does not.",
    state: "no",
    tag: "designed, not built",
  },
];

const TRUST = [
  {
    title: "It physically cannot change your data",
    plain:
      "It is allowed to read, never to write. Every query is inspected before it runs, and the connection it uses has no write permission anyway, so there is nothing to bypass.",
    tech: "Parsed into a syntax tree with sqlglot rather than pattern-matched; the database is opened query_only on a separate engine.",
  },
  {
    title: "It cannot quietly invent numbers",
    plain:
      "The usual AI failure is a confident, wrong figure. Every number is checked against the actual query result before you see it. If it does not match, the sentence is removed and the score at the top drops.",
    tech: "Numeric claims are extracted per sentence and matched to the cited rows, allowing for rounding and unit changes.",
  },
  {
    title: "It cannot run up a bill",
    plain:
      "Every investigation has a hard ceiling on how long it runs and what it may spend. When it hits the limit it stops and says so rather than continuing quietly.",
    tech: "Four independent caps — steps, tokens, cost and wall time — enforced in the graph, not by the model's cooperation.",
  },
  {
    title: "It will not follow instructions hidden in your files",
    plain:
      "Someone can hide text in a document that tries to give the AI orders. Documents are treated as information to read, never as instructions to obey, and anything that looks like an attempt is flagged for you.",
    tech: "The demo corpus carries a realistic injection attempt: ingest trips eight signatures on it and none on the other eleven documents.",
  },
];

const FAQ = [
  [
    "How is this different from asking ChatGPT?",
    "A chatbot answers from memory and from what you paste in. This connects to your actual database, decides for itself what to look up, and shows its working. You can click any number and see the query that produced it. If it cannot produce evidence for a sentence, the sentence is deleted before you read it.",
  ],
  [
    "Could it break or change our data?",
    "No. It only ever reads. Queries are inspected before they run and anything that would change or remove data is refused, and separately the connection has no permission to write. You can try to get past both on the Data sources page.",
  ],
  [
    "What if it gets something wrong?",
    "Then you can see that it did, which is the point. Every claim links to its source and the report carries a score showing how much of it was verifiable. A wrong answer you can audit in ten seconds is far safer than a plausible one you cannot check.",
  ],
  [
    "Does it need an expensive AI subscription?",
    "Not to try it. The built-in questions run with no API key and no internet at all, which is also how the automated tests run. For free-form questions, point it at any OpenAI-compatible provider, including Groq's free tier or a model on your own machine via Ollama.",
  ],
  [
    "Is the data real?",
    "It is a realistic invention: two years of sales for a fictional company, built so there are genuine puzzles to find. Every figure in a report is calculated from those records.",
  ],
];

export async function landingPage(root) {
  const signedIn = Boolean(session.token);
  const cta = signedIn ? "/app/new" : "/signin";
  const ctaLabel = signedIn ? "Open the workspace" : "Try the demo";

  root.innerHTML = `
    <header class="site-header">
      <a class="brand" href="/" data-link>
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-name">Meridian</span>
      </a>
      <nav class="site-nav" aria-label="Main">
        <a href="#what">What it does</a>
        <a href="#how">How it works</a>
        <a href="#trust">Why trust it</a>
        <a href="#faq">Questions</a>
      </nav>
      <div class="header-actions">
        <button class="btn btn-ghost" id="theme-toggle" type="button" aria-label="Toggle theme">
          <span data-theme-icon>Light</span>
        </button>
        <a class="btn btn-primary" href="${cta}" data-link>${ctaLabel}</a>
      </div>
    </header>

    <section class="objective" aria-label="What this is for">
      <p>
        <span class="objective-label">The objective</span>
        Replace the two-day manual investigation behind questions like
        <em>"why did sales drop?"</em> with a two-minute answer where
        <strong>every single number can be traced back to the data it came from.</strong>
      </p>
    </section>

    <main>
      <section class="hero">
        <div class="hero-copy">
          <p class="eyebrow">Research assistant for business teams</p>
          <h1>Ask your company data<br /><span class="accent">a hard question.</span></h1>
          <p class="lede">
            Type a question the way you would ask a colleague &mdash; <em>"why did our European
            sales fall last quarter?"</em> Meridian queries your sales database, reads your
            internal memos, checks exchange rates, and writes a short answer.
          </p>
          <p class="lede lede-tight">
            The difference from a chatbot: <strong>every number comes with a receipt.</strong>
            Click any figure and see the exact data behind it. If it cannot back something up, it
            deletes the sentence rather than guessing.
          </p>
          <div class="hero-cta">
            <a class="btn btn-primary btn-lg" href="${cta}" data-link>${ctaLabel}</a>
            <a class="btn btn-ghost btn-lg" href="#how">See how it works</a>
          </div>
          <dl class="hero-stats">
            <div><dt>Sales records searched</dt><dd>4,491</dd></div>
            <div><dt>Automated tests, offline</dt><dd>95</dd></div>
            <div><dt>Mutations ever allowed</dt><dd>0</dd></div>
          </dl>
        </div>

        <aside class="hero-panel">
          <div class="window">
            <div class="window-bar">
              <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              <span class="window-title">"Why did EMEA revenue drop in Q3?"</span>
            </div>
            <div class="window-body">
              <ol class="plan">
                <li data-state="done"><span class="tick">[x]</span><span>Compare revenue in USD and local currency</span></li>
                <li data-state="done"><span class="tick">[x]</span><span>Measure the EUR/USD move</span></li>
                <li data-state="done"><span class="tick">[x]</span><span>Find accounts lost at the end of Q2</span></li>
              </ol>
              <div class="tool-card" data-state="done">
                <div class="tool-head">
                  <span class="tick" style="color:var(--good)">&check;</span>
                  <span class="tool-name">sql_query</span>
                  <span class="tool-meta">4 rows &middot; 11 ms</span>
                </div>
                <div class="tool-arg">SELECT quarter, SUM(subtotal_usd), SUM(subtotal_local) ...</div>
              </div>
              <article class="report">
                <header class="report-head">
                  <h3>It was the exchange rate, not demand</h3>
                  <span class="badge badge-good">94% verified</span>
                </header>
                <p>
                  Reported revenue fell <strong>5.7%</strong> to $8,926,124
                  <cite>S1</cite>, but in local currency it <strong>rose 2.2%</strong>
                  <cite>S1</cite>. The euro fell from $1.09 to $1.00 <cite>S2</cite>, and one
                  account worth 9.5% of Q2 did not renew <cite>S3</cite>.
                </p>
              </article>
            </div>
          </div>
          <p class="demo-caption">A real answer. Open the workspace to run it yourself.</p>
        </aside>
      </section>

      <section class="band band-alt" id="what">
        <h2>What problem this solves</h2>
        <p class="band-lede">
          A question like "why did European sales drop?" has no single answer sitting in a
          spreadsheet. Someone has to go and investigate.
        </p>
        <div class="compare">
          <article class="compare-col">
            <h3>How it works today</h3>
            <ol class="plain-list">
              <li>An analyst gets the question on Monday.</li>
              <li>They write queries, export to Excel, build a pivot table.</li>
              <li>They dig through memos and old decks for context.</li>
              <li>They look up what the exchange rate did.</li>
              <li>They write it up. It lands Wednesday.</li>
              <li>Someone asks where a number came from. Nobody is quite sure.</li>
            </ol>
          </article>
          <article class="compare-col highlight">
            <h3>With Meridian</h3>
            <ol class="plain-list">
              <li>You type the question in plain English.</li>
              <li>It shows its plan first; you approve or change it.</li>
              <li>It runs the queries and reads the documents itself.</li>
              <li>You get a written answer in a couple of minutes.</li>
              <li>Every number is clickable and shows its source.</li>
              <li>Anything it cannot prove is removed, not guessed.</li>
            </ol>
          </article>
        </div>
        <p class="band-note">
          It is not replacing the analyst. It does the fetching and cross-checking so they spend
          their time on judgement instead of exports.
        </p>
      </section>

      <section class="band" id="how">
        <h2>How it works, step by step</h2>
        <p class="band-lede">
          Six stages. Four are built and two are not, and the tags say which. Steps 1, 3 and 5 are
          what runs when you ask a question.
        </p>
        <ol class="steps">
          ${STEPS.map(
            (step) => `
            <li data-built="${step.state}">
              <span class="step-n">${step.n}</span>
              <h3>${escapeHtml(step.title)}</h3>
              <p>${escapeHtml(step.body)}</p>
              <span class="step-tag ${step.state === "built" ? "built" : step.state === "partial" ? "partial" : "planned"}">${escapeHtml(step.tag)}</span>
            </li>`,
          ).join("")}
        </ol>
      </section>

      <section class="band band-alt" id="trust">
        <h2>Why you can trust it with your database</h2>
        <p class="band-lede">
          Giving an AI access to company data is a reasonable thing to be nervous about. These are
          the specific protections, in plain terms.
        </p>
        <div class="cards">
          ${TRUST.map(
            (card) => `
            <article class="card">
              <h3>${escapeHtml(card.title)}</h3>
              <p class="card-plain">${escapeHtml(card.plain)}</p>
              <p class="card-tech">${escapeHtml(card.tech)}</p>
            </article>`,
          ).join("")}
        </div>
        <p class="band-note">
          You can try to break the guard yourself on the Data sources page: type
          <code>DROP TABLE orders</code> and watch it refused with a reason, then run a harmless
          query that contains the word "delete" and watch it allowed.
        </p>
      </section>

      <section class="band" id="faq">
        <h2>Common questions</h2>
        <div class="faq">
          ${FAQ.map(
            ([question, answer]) => `
            <details>
              <summary>${escapeHtml(question)}</summary>
              <p>${escapeHtml(answer)}</p>
            </details>`,
          ).join("")}
        </div>
      </section>

      <section class="band band-alt cta-band">
        <h2>See it work</h2>
        <p class="band-lede">
          Three questions answer with no API key at all. Free-form questions use whichever model
          this deployment is configured with.
        </p>
        <a class="btn btn-primary btn-lg" href="${cta}" data-link>${ctaLabel}</a>
      </section>
    </main>

    <footer class="site-footer">
      <div>
        <span class="brand-mark small" aria-hidden="true"></span>
        <strong>Meridian</strong>
        <p class="muted">Ask your business data a hard question.<br />Get an answer you can check.</p>
      </div>
      <nav aria-label="Footer">
        <a href="/api/docs">Developer API</a>
        <a href="/health/ready">System status</a>
        <a href="/signin" data-link>Sign in</a>
      </nav>
    </footer>`;

  const toggle = $("#theme-toggle");
  toggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("meridian.theme", next);
    toggle.querySelector("[data-theme-icon]").textContent = next === "dark" ? "Light" : "Dark";
  });
  toggle.querySelector("[data-theme-icon]").textContent =
    document.documentElement.dataset.theme === "dark" ? "Light" : "Dark";

  void navigate;
}
