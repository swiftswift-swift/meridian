"""Generates two years of company data containing three deliberate stories.

The stories exist so the agent has something real to find, and so the demo is honest: every
number in a report is computed from these rows, not written into a fixture.

1. EMEA Q3 2025 revenue drop. Two causes, with currency the larger one. List prices are set in
   local currency at the start of each financial year and are not re-based intra-year, so an
   order's local amount is fixed by `REFERENCE_FX` while its USD amount is the conversion at the
   rate on the order date. When the euro weakens, USD revenue falls while local-currency revenue
   does not. On top of that, one large account (Helvetica Logistics) churns at the end of Q2.
   An agent that looks only at `subtotal_usd` concludes demand collapsed; one that compares
   `subtotal_local` with `subtotal_usd` finds the real answer.

2. A fast-growing, low-margin product line. "Edge Telemetry" roughly triples over the period
   while carrying a 22% gross margin against a company average in the low sixties, so growth and
   profitability disagree.

3. A poor-ROI campaign. The EMEA "Quantum Leap" campaign returns about 0.4x its spend against
   other campaigns returning 2.8x to 4.5x.

Generation is seeded, so running the seed twice produces identical rows and the figures quoted in
the README stay true.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

# A fixed seed is what makes the data reproducible, and reproducibility is what lets the
# evaluation suite assert on exact figures.
RANDOM_SEED = 20_260_104

START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 12, 31)

REGIONS = [(1, "EMEA", "EMEA"), (2, "Americas", "AMER"), (3, "Asia Pacific", "APAC")]

CURRENCIES = [
    ("USD", "US Dollar", "$"),
    ("EUR", "Euro", "€"),
    ("GBP", "Pound Sterling", "£"),
    ("JPY", "Japanese Yen", "¥"),
    ("AUD", "Australian Dollar", "A$"),
]

COUNTRIES = [
    (1, 1, "Germany", "DE", "EUR"),
    (2, 1, "France", "FR", "EUR"),
    (3, 1, "United Kingdom", "GB", "GBP"),
    (4, 1, "Switzerland", "CH", "EUR"),
    (5, 2, "United States", "US", "USD"),
    (6, 2, "Canada", "CA", "USD"),
    (7, 2, "Brazil", "BR", "USD"),
    (8, 3, "Japan", "JP", "JPY"),
    (9, 3, "Australia", "AU", "AUD"),
    (10, 3, "Singapore", "SG", "USD"),
    (11, 1, "Netherlands", "NL", "EUR"),
    (12, 1, "Spain", "ES", "EUR"),
    (13, 1, "Italy", "IT", "EUR"),
]

# gross_margin_pct is the planted contrast: Edge Telemetry grows fastest and earns least.
PRODUCT_LINES = [
    (1, "Core Analytics", "Platform", 68.0),
    (2, "Forecast Suite", "Platform", 64.0),
    (3, "Edge Telemetry", "Hardware", 22.0),
    (4, "Advisory Services", "Services", 41.0),
]

PRODUCTS = [
    (1, 1, "Core Analytics Starter", "CA-100", 1200.0, 384.0),
    (2, 1, "Core Analytics Pro", "CA-200", 3600.0, 1152.0),
    (3, 1, "Core Analytics Enterprise", "CA-300", 9800.0, 3136.0),
    (4, 2, "Forecast Suite Standard", "FS-100", 2400.0, 864.0),
    (5, 2, "Forecast Suite Advanced", "FS-200", 6200.0, 2232.0),
    (6, 3, "Edge Sensor Pack", "ET-100", 850.0, 663.0),
    (7, 3, "Edge Gateway", "ET-200", 2100.0, 1638.0),
    (8, 3, "Edge Fleet Bundle", "ET-300", 7400.0, 5772.0),
    (9, 4, "Onboarding Programme", "AS-100", 15000.0, 8850.0),
    (10, 4, "Quarterly Business Review", "AS-200", 4500.0, 2655.0),
]

# (id, name, country_id, segment, signed_on, churned_on, annual_contract_usd)
# Helvetica Logistics is story 1's lost key account. Its contract is large enough to matter and
# small enough that currency remains the larger explanation of the Q3 decline, which is the
# ordering the EMEA business review document claims.
CUSTOMERS: list[tuple[int, str, int, str, str, str | None, float]] = [
    (1, "Helvetica Logistics", 4, "Enterprise", "2024-01-15", "2025-06-30", 820_000.0),
    (2, "Rheinmetrik GmbH", 1, "Enterprise", "2024-01-20", None, 1_240_000.0),
    (3, "Bourbon Analytique", 2, "Mid-Market", "2024-02-05", None, 420_000.0),
    (4, "Thames Data Works", 3, "Enterprise", "2024-01-08", None, 980_000.0),
    (5, "Alpen Retail Group", 1, "Mid-Market", "2024-03-12", None, 365_000.0),
    (6, "Normandy Foods", 2, "Mid-Market", "2024-04-02", None, 288_000.0),
    (7, "Northwind Industrial", 5, "Enterprise", "2024-01-10", None, 2_100_000.0),
    (8, "Cascadia Freight", 5, "Mid-Market", "2024-02-18", None, 540_000.0),
    (9, "Maple Ridge Systems", 6, "Mid-Market", "2024-03-01", None, 410_000.0),
    (10, "Sao Paulo Mobility", 7, "Mid-Market", "2024-05-20", None, 320_000.0),
    (11, "Great Lakes Manufacturing", 5, "Enterprise", "2024-01-25", None, 1_480_000.0),
    (12, "Sakura Robotics", 8, "Enterprise", "2024-02-01", None, 1_150_000.0),
    (13, "Harbour Logistics AU", 9, "Mid-Market", "2024-03-18", None, 395_000.0),
    (14, "Lion City Analytics", 10, "Mid-Market", "2024-04-10", None, 350_000.0),
    (15, "Kyoto Precision", 8, "Mid-Market", "2024-06-05", None, 275_000.0),
    (16, "Outback Energy", 9, "Enterprise", "2024-07-15", None, 860_000.0),
    # Additional EMEA accounts. More accounts means quarterly aggregates are driven by the
    # planted effects rather than by the sampling noise of a handful of customers.
    (17, "Batavia Interlink", 11, "Enterprise", "2024-01-12", None, 1_020_000.0),
    (18, "Iberia Analitica", 12, "Mid-Market", "2024-02-22", None, 395_000.0),
    (19, "Milano Dati", 13, "Mid-Market", "2024-03-05", None, 430_000.0),
    (20, "Hansa Werke", 1, "Enterprise", "2024-01-30", None, 1_110_000.0),
    (21, "Loire Systemes", 2, "Mid-Market", "2024-04-18", None, 335_000.0),
    (22, "Pennine Freight", 3, "Mid-Market", "2024-05-08", None, 360_000.0),
]

# Quarterly average FX rates to USD. The 2025 Q2 to Q3 fall in EUR and GBP is story 1.
FX_BY_QUARTER: dict[str, dict[str, float]] = {
    "2024Q1": {"USD": 1.0, "EUR": 1.088, "GBP": 1.268, "JPY": 0.00662, "AUD": 0.658},
    "2024Q2": {"USD": 1.0, "EUR": 1.081, "GBP": 1.263, "JPY": 0.00641, "AUD": 0.662},
    "2024Q3": {"USD": 1.0, "EUR": 1.098, "GBP": 1.300, "JPY": 0.00680, "AUD": 0.669},
    "2024Q4": {"USD": 1.0, "EUR": 1.070, "GBP": 1.282, "JPY": 0.00660, "AUD": 0.652},
    "2025Q1": {"USD": 1.0, "EUR": 1.084, "GBP": 1.274, "JPY": 0.00668, "AUD": 0.631},
    "2025Q2": {"USD": 1.0, "EUR": 1.092, "GBP": 1.291, "JPY": 0.00675, "AUD": 0.642},
    # The planted move: EUR 1.092 -> 0.995 is -8.9%, GBP 1.291 -> 1.192 is -7.7%.
    "2025Q3": {"USD": 1.0, "EUR": 0.995, "GBP": 1.192, "JPY": 0.00648, "AUD": 0.629},
    "2025Q4": {"USD": 1.0, "EUR": 1.021, "GBP": 1.215, "JPY": 0.00652, "AUD": 0.634},
}

# Local list prices are derived from USD list prices once a year, at these rates, and are not
# re-based intra-year. This is what makes subtotal_local stable while subtotal_usd moves with the
# market, and it is the mechanism the pricing policy document describes.
REFERENCE_FX: dict[int, dict[str, float]] = {
    2024: FX_BY_QUARTER["2024Q1"],
    2025: FX_BY_QUARTER["2025Q1"],
}

EMEA_COUNTRY_IDS = frozenset({1, 2, 3, 4, 11, 12, 13})


def quarter_of(day: date) -> str:
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"


@dataclass(slots=True)
class GeneratedData:
    orders: list[tuple[object, ...]]
    order_items: list[tuple[object, ...]]
    marketing_spend: list[tuple[object, ...]]


def _line_growth_multiplier(product_line_id: int, day: date) -> float:
    """How a product line's volume changes over the two years.

    Edge Telemetry (line 3) is the planted growth story: it roughly triples. Everything else grows
    modestly so the contrast is visible without being absurd.
    """
    months_elapsed = (day.year - START_DATE.year) * 12 + (day.month - START_DATE.month)
    progress = months_elapsed / 23  # 0.0 at the start, 1.0 at the end
    if product_line_id == 3:
        return 0.75 + 1.40 * progress
    if product_line_id == 4:
        return 0.92 + 0.25 * progress
    # Deliberately shallow. A steeper underlying trend would grow EMEA faster than the churned
    # account shrinks it, and the Q3 decline the demo is built around would disappear.
    return 0.97 + 0.18 * progress


def _emea_seasonal_factor(day: date) -> float:
    """Mild seasonality, so quarter comparisons are not suspiciously flat.

    Kept small deliberately. A pronounced summer dip would be a third explanation for the Q3
    decline and would muddy the currency story the demo is built to show.
    """
    if day.month in (7, 8):
        return 0.97
    if day.month == 12:
        return 1.05
    return 1.0


def generate() -> GeneratedData:
    rng = random.Random(RANDOM_SEED)
    orders: list[tuple[object, ...]] = []
    order_items: list[tuple[object, ...]] = []

    country_currency = {country[0]: country[4] for country in COUNTRIES}
    product_by_id = {product[0]: product for product in PRODUCTS}
    order_id = 0
    item_id = 0

    day = START_DATE
    while day <= END_DATE:
        # Business days only; a flat seven-day cadence makes weekly aggregates look synthetic.
        if day.weekday() < 5:
            quarter = quarter_of(day)
            for customer in CUSTOMERS:
                customer_id, _, country_id, segment, signed_on, churned_on, acv = customer
                if date.fromisoformat(signed_on) > day:
                    continue
                if churned_on is not None and date.fromisoformat(churned_on) < day:
                    continue

                # Larger accounts order more often. Tuned so two years yields a few thousand
                # orders: enough that quarterly aggregates are stable, few enough to stay fast.
                order_probability = 0.22 + min(0.34, acv / 4_000_000)
                if segment == "Enterprise":
                    order_probability *= 1.2
                if rng.random() > order_probability:
                    continue

                currency = country_currency[country_id]
                spot_rate = FX_BY_QUARTER[quarter][currency]
                reference_rate = REFERENCE_FX[day.year][currency]
                # Local price was fixed at the year's reference rate; USD is today's conversion.
                # A weaker local currency therefore reduces USD revenue and leaves local revenue
                # untouched, which is the whole mechanism behind story 1.
                fx_factor = spot_rate / reference_rate

                order_id += 1
                line_count = rng.choices([1, 2, 3], weights=[0.5, 0.33, 0.17])[0]
                chosen = rng.sample(sorted(product_by_id), k=line_count)

                local_subtotal = 0.0
                pending_items: list[tuple[object, ...]] = []
                for product_id in chosen:
                    _, product_line_id, _, _, list_price_usd, _ = product_by_id[product_id]
                    multiplier = _line_growth_multiplier(product_line_id, day)
                    if country_id in EMEA_COUNTRY_IDS:
                        multiplier *= _emea_seasonal_factor(day)
                    quantity = max(1, round(rng.triangular(1, 6, 2) * multiplier))
                    discount = rng.choice([0.0, 0.0, 0.0, 0.05, 0.1, 0.15])

                    # Local-currency value of the line, at the year's fixed local price.
                    local_price = list_price_usd / reference_rate
                    local_line = quantity * local_price * (1 - discount)
                    local_subtotal += local_line

                    # The realised USD figures follow from the spot rate, so order_items always
                    # sums to the order's subtotal_usd.
                    realised_unit_price_usd = round(list_price_usd * fx_factor, 4)
                    line_total_usd = round(local_line * spot_rate, 2)
                    item_id += 1
                    pending_items.append(
                        (
                            item_id,
                            order_id,
                            product_id,
                            quantity,
                            realised_unit_price_usd,
                            discount,
                            line_total_usd,
                        )
                    )

                subtotal_local = round(local_subtotal, 2)
                subtotal_usd = round(sum(item[6] for item in pending_items), 2)  # type: ignore[misc]
                status = "cancelled" if rng.random() < 0.015 else "fulfilled"
                orders.append(
                    (
                        order_id,
                        customer_id,
                        day.isoformat(),
                        currency,
                        spot_rate,
                        subtotal_local,
                        subtotal_usd,
                        status,
                    )
                )
                order_items.extend(pending_items)
        day += timedelta(days=1)

    return GeneratedData(
        orders=orders,
        order_items=order_items,
        marketing_spend=_generate_marketing_spend(rng),
    )


def _generate_marketing_spend(rng: random.Random) -> list[tuple[object, ...]]:
    """Campaign spend, including the planted poor-ROI campaign.

    "Quantum Leap" returns roughly 0.4x its spend while the others return 2.8x to 4.5x, so the
    comparison is unambiguous without being a single outlier month.
    """
    campaigns = [
        (1, "Signal Boost", "paid_search", 2.9),
        (1, "Quantum Leap", "brand_video", 0.4),
        (1, "Field Events EMEA", "events", 3.1),
        (2, "Pipeline Accelerator", "paid_search", 4.5),
        (2, "Partner Co-Marketing", "partner", 3.4),
        (3, "APAC Expansion", "paid_social", 2.8),
    ]
    rows: list[tuple[object, ...]] = []
    row_id = 0
    for year in (2024, 2025):
        for month in range(1, 13):
            for region_id, campaign, channel, roi in campaigns:
                # Quantum Leap only runs from 2025, which makes it a current problem rather than
                # historical noise.
                if campaign == "Quantum Leap" and year == 2024:
                    continue
                base = {"paid_search": 48_000, "brand_video": 120_000, "events": 65_000}.get(
                    channel, 40_000
                )
                spend = round(base * rng.uniform(0.85, 1.15), 2)
                attributed = round(spend * roi * rng.uniform(0.9, 1.1), 2)
                row_id += 1
                rows.append(
                    (
                        row_id,
                        region_id,
                        campaign,
                        channel,
                        f"{year}-{month:02d}",
                        spend,
                        attributed,
                    )
                )
    return rows
