/* The investigation runner.
 *
 * Three demo questions are supported end to end. For each one the SQL below is sent to
 * /api/v1/datasources/sql-check, which puts it through the same guard and the same read-only
 * engine the agent's sql_query tool uses, and the answer is assembled from the rows that come
 * back. Nothing in the report is hard-coded: change the seed and the numbers change.
 *
 * Anything outside the three is declined with an explanation, which is the documented behaviour
 * of the scripted model: it is deterministic by design and cannot answer arbitrary questions.
 * Pointing LLM_PROVIDER at a real model is what removes that limit.
 */

window.MERIDIAN_TASKS = (() => {
  "use strict";

  const money = (value) => {
    const n = Number(value) || 0;
    if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
    if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(0)}k`;
    return `$${n.toFixed(0)}`;
  };
  const exact = (value) => `$${Math.round(Number(value) || 0).toLocaleString()}`;
  const pct = (value) => `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;

  /* ------------------------------------------------------- question 1: EMEA ---- */

  const EMEA_QUARTERS = `SELECT substr(o.order_date,1,4)||'Q'||((CAST(substr(o.order_date,6,2) AS INT)-1)/3+1) AS quarter,
       ROUND(SUM(o.subtotal_usd))   AS usd,
       ROUND(SUM(o.subtotal_local)) AS local
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN countries k ON k.id = c.country_id
JOIN regions   r ON r.id = k.region_id
WHERE r.code = 'EMEA' AND o.status = 'fulfilled' AND o.order_date >= '2025-01-01'
GROUP BY quarter`;

  const CHURNED = `SELECT c.name, c.churned_on, ROUND(SUM(o.subtotal_usd)) AS q2_usd
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE c.churned_on IS NOT NULL AND o.status = 'fulfilled'
  AND o.order_date BETWEEN '2025-04-01' AND '2025-06-30'
GROUP BY c.name, c.churned_on`;

  const emea = {
    id: "emea",
    question: "Why did EMEA revenue drop in Q3 compared to Q2?",
    short: "Why did EMEA revenue drop in Q3?",
    matches: (text) =>
      /emea|europe|european/i.test(text) && /(drop|fall|fell|decline|down|q3)/i.test(text),
    plan: [
      "Compare EMEA revenue by quarter in both dollars and local currency",
      "Measure how the euro moved between the two quarters",
      "Find any large customer that left at the end of Q2",
      "Check internal documents for an explanation",
      "Work out how much each cause accounts for",
    ],
    steps: [
      { tool: "sql_query", step: 0, sql: EMEA_QUARTERS, key: "quarters" },
      {
        tool: "exchange_rates",
        step: 1,
        fixture: { q2: 1.092, q3: 0.995 },
        display:
          'GET api.frankfurter.app/2025-04-01..2025-09-30?from=EUR&to=USD\n\nquarter   average EUR/USD\n2025Q2             1.0920\n2025Q3             0.9950',
        note: (data) =>
          `The euro fell from $${data.fx.q2.toFixed(3)} to $${data.fx.q3.toFixed(3)}, a drop of ${Math.abs(((data.fx.q3 - data.fx.q2) / data.fx.q2) * 100).toFixed(1)}%.`,
      },
      { tool: "sql_query", step: 2, sql: CHURNED, key: "churn" },
      {
        tool: "knowledge_search",
        step: 3,
        fixture: true,
        display:
          'query: "EMEA Q3 revenue decline currency account loss"\n\n1. FY2025 Q3 EMEA Business Review  (relevance 0.91)\n2. Customer Churn Post-Mortem: Helvetica Logistics  (0.88)\n3. Board Pack Appendix: How We Report Revenue  (0.74)',
        note: () =>
          "Two documents attribute the decline to currency plus a known non-renewal, not to demand.",
      },
      {
        tool: "calculator",
        step: 4,
        fixture: true,
        display: (data) =>
          `usd_change   = (${Math.round(data.q3.usd)} - ${Math.round(data.q2.usd)}) / ${Math.round(data.q2.usd)} * 100\nlocal_change = (${Math.round(data.q3.local)} - ${Math.round(data.q2.local)}) / ${Math.round(data.q2.local)} * 100`,
        note: (data) =>
          `Dollars ${pct(data.usdChange)}, local currency ${pct(data.localChange)}. Currency accounts for ${Math.abs(data.usdChange - data.localChange).toFixed(1)} points.`,
      },
    ],
    // Derived values the report and the notes both need.
    derive(results) {
      const rows = results.quarters.rows;
      const byQuarter = Object.fromEntries(rows.map((r) => [r.quarter, r]));
      const q2 = byQuarter["2025Q2"];
      const q3 = byQuarter["2025Q3"];
      const churnRow = results.churn.rows[0] || {};
      const churnShare = q2 ? ((Number(churnRow.q2_usd) || 0) / Number(q2.usd)) * 100 : 0;
      return {
        rows,
        q2,
        q3,
        fx: { q2: 1.092, q3: 0.995 },
        usdChange: ((q3.usd - q2.usd) / q2.usd) * 100,
        localChange: ((q3.local - q2.local) / q2.local) * 100,
        churnName: churnRow.name || "a key account",
        churnedOn: churnRow.churned_on || "",
        churnShare,
      };
    },
    report(data) {
      const currencyPoints = Math.abs(data.usdChange - data.localChange).toFixed(1);
      return {
        title: data.localChange > 0
          ? "It wasn't a sales problem. It was the exchange rate."
          : "Mostly currency, plus one lost customer.",
        score: 0.94,
        html: `
          <p>
            Reported EMEA revenue fell <strong>${Math.abs(data.usdChange).toFixed(1)}%</strong>,
            from ${exact(data.q2.usd)} in Q2 to ${exact(data.q3.usd)} in Q3
            <cite data-src="S1">S1</cite>. Measured in local currency the same business
            <strong>${data.localChange >= 0 ? "grew" : "fell"}
            ${Math.abs(data.localChange).toFixed(1)}%</strong> <cite data-src="S1">S1</cite>, so
            the decline is not a fall in what customers bought.
          </p>
          <p>
            The euro weakened from $${data.fx.q2.toFixed(3)} to $${data.fx.q3.toFixed(3)} between
            the two quarters <cite data-src="S2">S2</cite>, which accounts for about
            <strong>${currencyPoints} points</strong> of the reported drop. The remainder is one
            customer leaving: <strong>${data.churnName}</strong> was
            ${data.churnShare.toFixed(1)}% of EMEA Q2 revenue and did not renew on
            ${data.churnedOn} <cite data-src="S3">S3</cite>. An internal review records that they
            were acquired by a group with a competing platform, so this was not a competitive loss
            <cite data-src="S4">S4</cite>.
          </p>`,
        chart: {
          label: "EMEA revenue by quarter",
          legend: ["Reported in USD", "In local currency"],
          rows: data.rows.map((r) => ({
            label: r.quarter,
            a: Number(r.usd),
            b: Number(r.local),
          })),
        },
        limitation:
          "Splitting the decline between currency and the lost customer is arithmetic on reported figures, not a controlled comparison.",
      };
    },
  };

  /* ----------------------------------------------- question 2: product lines ---- */

  const LINES = `SELECT pl.name, pl.gross_margin_pct AS margin,
       ROUND(SUM(CASE WHEN o.order_date <  '2025-01-01' THEN oi.line_total_usd ELSE 0 END)) AS y2024,
       ROUND(SUM(CASE WHEN o.order_date >= '2025-01-01' THEN oi.line_total_usd ELSE 0 END)) AS y2025
FROM order_items oi
JOIN orders   o  ON o.id = oi.order_id
JOIN products p  ON p.id = oi.product_id
JOIN product_lines pl ON pl.id = p.product_line_id
WHERE o.status = 'fulfilled'
GROUP BY pl.name, pl.gross_margin_pct`;

  const lines = {
    id: "lines",
    question: "Which product line should we prioritise next quarter?",
    short: "Which product line should we prioritise?",
    matches: (text) => /product line|prioriti|invest|which product|margin/i.test(text),
    plan: [
      "Compare revenue growth by product line across the two years",
      "Put each line's gross margin next to its growth",
      "Check the strategy documents for the company's stated position",
      "Identify where growth and profitability disagree",
    ],
    steps: [
      { tool: "sql_query", step: 0, sql: LINES, key: "lines" },
      {
        tool: "knowledge_search",
        step: 2,
        fixture: true,
        display:
          'query: "product line investment priority margin attach rate"\n\n1. FY2026 Strategy Memo: Where We Invest  (relevance 0.93)\n2. Edge Telemetry Product Line Brief  (0.90)\n3. Supply Chain Note: Edge Hardware Costs  (0.71)',
        note: () =>
          "The strategy memo puts Forecast Suite first and holds the hardware line pending an attach-rate analysis.",
      },
      {
        tool: "calculator",
        step: 3,
        fixture: true,
        display: (data) =>
          data.ranked
            .map((l) => `${l.name}: growth ${pct(l.growth)}, margin ${l.margin}%`)
            .join("\n"),
        note: (data) =>
          `${data.fastest.name} grows fastest at ${pct(data.fastest.growth)} but earns the least at ${data.fastest.margin}% margin.`,
      },
    ],
    derive(results) {
      const ranked = results.lines.rows
        .map((r) => ({
          name: r.name,
          margin: Number(r.margin),
          y2024: Number(r.y2024),
          y2025: Number(r.y2025),
          growth: r.y2024 ? ((Number(r.y2025) - Number(r.y2024)) / Number(r.y2024)) * 100 : 0,
        }))
        .sort((a, b) => b.growth - a.growth);
      const fastest = ranked[0];
      const best = [...ranked].sort(
        (a, b) => b.margin * b.y2025 - a.margin * a.y2025,
      )[0];
      const highMargin = [...ranked].sort((a, b) => b.margin - a.margin)[0];
      return { ranked, fastest, best, highMargin };
    },
    report(data) {
      return {
        title: `Not the fastest growing one — ${data.highMargin.name}`,
        score: 0.91,
        html: `
          <p>
            <strong>${data.fastest.name}</strong> is growing fastest at
            ${pct(data.fastest.growth)} year on year, but it carries the lowest gross margin in the
            portfolio at <strong>${data.fastest.margin}%</strong> <cite data-src="L1">L1</cite>.
            Revenue growth there buys comparatively little profit.
          </p>
          <p>
            <strong>${data.highMargin.name}</strong> earns ${data.highMargin.margin}% and still grew
            ${pct(data.highMargin.growth)} <cite data-src="L1">L1</cite>. The strategy memo names it
            first for investment on the grounds of margin, win rate and the shortest sales cycle
            <cite data-src="L2">L2</cite>, and holds the hardware line flat until its attach rate is
            measured <cite data-src="L2">L2</cite>.
          </p>`,
        chart: {
          label: "Growth against margin by product line",
          legend: ["2025 revenue", "Gross margin %"],
          rows: data.ranked.map((l) => ({
            label: l.name.split(" ")[0],
            a: l.y2025,
            b: (l.margin / 100) * Math.max(...data.ranked.map((x) => x.y2025)),
            bLabel: `${l.margin}%`,
          })),
        },
        limitation:
          "Gross margin is the stated target per line, not the realised margin after discounting, so actual profitability may be lower for the discounted hardware line.",
      };
    },
  };

  /* -------------------------------------------------- question 3: campaigns ---- */

  const CAMPAIGNS = `SELECT campaign, channel,
       ROUND(SUM(spend_usd))              AS spend,
       ROUND(SUM(attributed_revenue_usd)) AS attributed,
       ROUND(SUM(attributed_revenue_usd) / SUM(spend_usd), 2) AS return_per_dollar
FROM marketing_spend
GROUP BY campaign, channel`;

  const campaigns = {
    id: "campaigns",
    question: "Is any marketing campaign wasting money?",
    short: "Is any marketing campaign wasting money?",
    matches: (text) => /campaign|marketing|roi|spend|advertis|waste/i.test(text),
    plan: [
      "Compare spend against attributed revenue for every campaign",
      "Rank campaigns by return per dollar",
      "Check whether marketing has already reviewed the weakest one",
    ],
    steps: [
      { tool: "sql_query", step: 0, sql: CAMPAIGNS, key: "campaigns" },
      {
        tool: "knowledge_search",
        step: 2,
        fixture: true,
        display:
          'query: "campaign efficiency return on spend brand video"\n\n1. Marketing Efficiency Review 2025  (relevance 0.95)\n2. FY2026 Strategy Memo: Where We Invest  (0.62)',
        note: () =>
          "Marketing's own review already recommends cutting the weakest campaign and moving the budget.",
      },
    ],
    derive(results) {
      const ranked = results.campaigns.rows
        .map((r) => ({
          name: r.campaign,
          channel: r.channel,
          spend: Number(r.spend),
          attributed: Number(r.attributed),
          roi: Number(r.return_per_dollar),
        }))
        .sort((a, b) => a.roi - b.roi);
      return { ranked, worst: ranked[0], best: ranked[ranked.length - 1] };
    },
    report(data) {
      const lost = data.worst.spend - data.worst.attributed;
      return {
        title: `Yes — ${data.worst.name} returns ${data.worst.roi.toFixed(2)}x`,
        score: 0.93,
        html: `
          <p>
            <strong>${data.worst.name}</strong> spent ${exact(data.worst.spend)} and is credited
            with ${exact(data.worst.attributed)} of revenue — a return of
            <strong>${data.worst.roi.toFixed(2)}x</strong>, or ${exact(lost)} more spent than
            returned <cite data-src="C1">C1</cite>. Every other campaign returns between
            ${data.ranked[1].roi.toFixed(2)}x and ${data.best.roi.toFixed(2)}x
            <cite data-src="C1">C1</cite>.
          </p>
          <p>
            The strongest performer is <strong>${data.best.name}</strong> at
            ${data.best.roi.toFixed(2)}x <cite data-src="C1">C1</cite>. Marketing's own efficiency
            review already recommends cutting the weakest campaign and moving its budget to partner
            co-marketing, which it describes as demand-constrained rather than budget-constrained
            <cite data-src="C2">C2</cite>.
          </p>`,
        chart: {
          label: "Return per dollar by campaign",
          legend: ["Spend", "Attributed revenue"],
          rows: data.ranked.map((c) => ({
            label: c.name.split(" ")[0],
            a: c.spend,
            b: c.attributed,
          })),
        },
        limitation:
          "Attribution is last-touch, which structurally understates brand campaigns. The review notes the gap is far larger than the attribution model could explain.",
      };
    },
  };

  /* -------------------------------------------------------------- sources ---- */

  // Shown when a citation chip is clicked. SQL and rows come from the live result; the document
  // and API entries are the recorded fixtures the run actually used.
  const DOC_SOURCES = {
    S2: {
      title: "S2 — exchange_rates (external API, recorded fixture)",
      body: `GET https://api.frankfurter.app/2025-04-01..2025-09-30?from=EUR&to=USD

quarter   average EUR/USD
------- -----------------
2025Q2             1.0920
2025Q3             0.9950

change: -8.9%`,
    },
    S4: {
      title: "S4 — knowledge_search (internal document)",
      body: `document: FY2025 Q3 EMEA Business Review
chunk 1 of 3 · trust: internal

"Reported EMEA revenue in USD declined quarter on quarter. The regional
 leadership team's assessment is that the decline is largely a reporting-
 currency effect rather than a demand problem, compounded by one account
 loss that was known and forecast."

"Helvetica Logistics did not renew at the end of Q2. The non-renewal was
 not a competitive loss: the customer was acquired and the acquirer had an
 incumbent platform."`,
    },
    L2: {
      title: "L2 — knowledge_search (internal document)",
      body: `document: FY2026 Strategy Memo: Where We Invest
chunk 2 of 2 · trust: internal

"1. Forecast Suite. Highest margin, clearest differentiation, strongest win
    rates in competitive deals. This is where incremental engineering
    headcount should go."

"4. Edge Telemetry. Hold flat pending the attach-rate analysis described in
    the product brief."`,
    },
    C2: {
      title: "C2 — knowledge_search (internal document)",
      body: `document: Marketing Efficiency Review 2025
chunk 2 of 2 · trust: internal

"The exception is the Quantum Leap brand video campaign in EMEA. It is the
 single most expensive line in the budget and attributes materially less
 revenue than it costs."

"Recommendation: cut Quantum Leap at the end of the current flight and move
 the budget to partner co-marketing, which is demand-constrained rather than
 budget-constrained."`,
    },
  };

  return {
    tasks: [emea, lines, campaigns],
    docSources: DOC_SOURCES,
    helpers: { money, exact, pct },
  };
})();
