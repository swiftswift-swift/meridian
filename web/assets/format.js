/* Turning database output into something a person can read.

   Column names come straight from SQL the model wrote, so they look like `subtotal_usd` and
   `attributed_revenue_usd`. Nobody outside the team reads those as "Revenue" and "Revenue from
   marketing". This module renames them, formats the values to match, and decides when a set of
   rows is worth drawing as a chart.

   The rules are derived from the column name rather than a fixed lookup, because the model
   invents its own aliases and a lookup would only cover the ones we happened to think of. */

const LOCALE = "en-US";

const EXACT_NAMES = {
  usd: "Revenue (USD)",
  local: "Revenue (local currency)",
  subtotal_usd: "Revenue (USD)",
  subtotal_local: "Revenue (local currency)",
  revenue_usd: "Revenue (USD)",
  attributed_revenue_usd: "Revenue credited to marketing",
  spend_usd: "Marketing spend",
  line_total_usd: "Line value",
  unit_price_usd: "Unit price",
  unit_cost_usd: "Unit cost",
  annual_contract_usd: "Annual contract value",
  gross_margin_pct: "Profit margin",
  discount_pct: "Discount",
  fx_rate_to_usd: "Exchange rate to USD",
  order_date: "Order date",
  signed_on: "Became a customer",
  churned_on: "Left on",
  iso_code: "Country code",
  currency_code: "Currency",
  product_line: "Product line",
  region_id: "Region",
  country_id: "Country",
  customer_id: "Customer",
  product_id: "Product",
  order_id: "Order",
  order_count: "Number of orders",
  customer_count: "Number of customers",
  n: "Count",
  cnt: "Count",
  qty: "Quantity",
  roi: "Return per pound spent",
  roi_pct: "Return on spend",
  return_per_dollar: "Return per dollar spent",
};

/* Suffixes that say what a value means, longest first so `_usd` does not shadow `_revenue_usd`. */
const SUFFIX_RULES = [
  { match: /_pct$|_percent$|^pct_/, label: (base) => `${base} (%)`, kind: "percent" },
  { match: /_usd$/, label: (base) => `${base} (USD)`, kind: "money" },
  { match: /_rate$/, label: (base) => `${base} rate`, kind: "number" },
];

export function prettyColumn(raw) {
  const key = String(raw).toLowerCase();
  if (EXACT_NAMES[key]) return EXACT_NAMES[key];

  for (const rule of SUFFIX_RULES) {
    if (rule.match.test(key)) {
      const base = humanise(key.replace(rule.match, ""));
      if (base) return rule.label(base);
    }
  }
  return humanise(key);
}

function humanise(key) {
  const words = String(key)
    .replace(/_/g, " ")
    .replace(/\bavg\b/g, "average")
    .replace(/\bpct\b/g, "percent")
    .replace(/\bqty\b/g, "quantity")
    .replace(/\bcust\b/g, "customer")
    .replace(/\brev\b/g, "revenue")
    .trim();
  if (!words) return "";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/* What kind of number a column holds, so the value can be formatted to match its name. */
export function columnKind(raw) {
  const key = String(raw).toLowerCase();
  // Percent first: "revenue_share_pct" contains "revenue", and testing money first turned a
  // 0.197 share into $0.20.
  if (/_pct$|percent|margin|discount|share|_rate$/.test(key)) return "percent";
  if (/_usd$|^usd$|^local$|price|cost|spend|revenue|contract/.test(key)) return "money";
  if (/_date$|_on$|^month$|^day$|^quarter$|^year$/.test(key)) return "text";
  if (/count|^n$|^cnt$|quantity|^orders$/.test(key)) return "count";
  return "auto";
}

export function formatValue(column, value) {
  if (value === null || value === undefined || value === "") return "—";
  const kind = columnKind(column);
  const numeric = typeof value === "number" ? value : Number(value);

  if (Number.isNaN(numeric) || typeof value === "string") return String(value);

  if (kind === "money") {
    return numeric.toLocaleString(LOCALE, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: Math.abs(numeric) >= 1000 ? 0 : 2,
    });
  }
  if (kind === "percent") {
    // A share can arrive as 0.071 or as 7.1 depending on how the query was written. Values at or
    // below 1 are treated as fractions, which is right far more often than it is wrong.
    const shown = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
    return `${shown.toFixed(1)}%`;
  }
  if (kind === "count" || Number.isInteger(numeric)) return numeric.toLocaleString(LOCALE);
  return numeric.toLocaleString(LOCALE, { maximumFractionDigits: 2 });
}

/* --- deciding whether a result is worth drawing ---------------------------------- */

const MIN_CHART_ROWS = 2;
const MAX_CHART_ROWS = 12;

/* A result can be charted when it has one text column to label the bars and at least one
   numeric column to size them. Anything wider or longer than that reads better as a table. */
export function chartSpec(columns, rows) {
  if (!rows || rows.length < MIN_CHART_ROWS || rows.length > MAX_CHART_ROWS) return null;

  const labelColumn = columns.find((c) => rows.every((r) => typeof r[c] === "string"));
  if (!labelColumn) return null;

  const numericColumns = columns.filter(
    (c) => c !== labelColumn && rows.every((r) => typeof r[c] === "number" && Number.isFinite(r[c])),
  );
  if (!numericColumns.length) return null;

  // Two series at most: a third bar per row stops being readable at this size.
  const [first, second] = numericColumns;
  const chartRows = rows.map((row) => ({
    label: String(row[labelColumn]),
    a: Number(row[first]),
    aLabel: formatValue(first, row[first]),
    ...(second === undefined
      ? {}
      : { b: Number(row[second]), bLabel: formatValue(second, row[second]) }),
  }));

  // Two series on one axis only make sense at comparable magnitudes; otherwise the smaller is
  // an invisible sliver and the chart misleads.
  if (second !== undefined) {
    const peakA = Math.max(...chartRows.map((r) => Math.abs(r.a)), 1);
    const peakB = Math.max(...chartRows.map((r) => Math.abs(r.b)), 1);
    const ratio = Math.max(peakA, peakB) / Math.min(peakA, peakB);
    if (ratio > 25) {
      return {
        rows: chartRows.map(({ label, a, aLabel }) => ({ label, a, aLabel })),
        legend: [prettyColumn(first)],
      };
    }
  }

  return {
    rows: chartRows,
    legend: second === undefined ? [prettyColumn(first)] : [prettyColumn(first), prettyColumn(second)],
  };
}
