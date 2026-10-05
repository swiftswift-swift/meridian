"""The sample company database: "Northwind Analytics".

This is a separate database from the product's own, reached through a read-only engine. The SQL
tool is given the allowlist built from `TABLE_COLUMNS` below, so the planner knows exactly what
it may query and the guard knows exactly what to refuse.

Kept as explicit DDL rather than ORM models because this schema is data the product reads, not
state the product owns, and a reviewer should be able to see the whole analytical schema in one
screen.
"""

from __future__ import annotations

from typing import Final

# Column lists double as the SQL guard's allowlist, so adding a column here is the single edit
# needed to expose it to the agent.
TABLE_COLUMNS: Final[dict[str, list[str]]] = {
    "regions": ["id", "name", "code"],
    "countries": ["id", "region_id", "name", "iso_code", "currency_code"],
    "currencies": ["code", "name", "symbol"],
    "product_lines": ["id", "name", "category", "gross_margin_pct"],
    "products": ["id", "product_line_id", "name", "sku", "unit_price_usd", "unit_cost_usd"],
    "customers": [
        "id",
        "name",
        "country_id",
        "segment",
        "signed_on",
        "churned_on",
        "annual_contract_usd",
    ],
    "orders": [
        "id",
        "customer_id",
        "order_date",
        "currency_code",
        "fx_rate_to_usd",
        "subtotal_local",
        "subtotal_usd",
        "status",
    ],
    "order_items": [
        "id",
        "order_id",
        "product_id",
        "quantity",
        "unit_price_usd",
        "discount_pct",
        "line_total_usd",
    ],
    "marketing_spend": [
        "id",
        "region_id",
        "campaign",
        "channel",
        "month",
        "spend_usd",
        "attributed_revenue_usd",
    ],
}

# A short human description per table, given to the planner so it can choose tables sensibly
# without first issuing exploratory queries.
TABLE_DESCRIPTIONS: Final[dict[str, str]] = {
    "regions": "Sales regions: EMEA, AMER, APAC.",
    "countries": "Countries within each region, with the local currency.",
    "currencies": "Currency reference data.",
    "product_lines": "Product families with their target gross margin percentage.",
    "products": "Individual products with unit price and unit cost in USD.",
    "customers": "Accounts, their country, segment, signing date and churn date if lost.",
    "orders": (
        "Order headers. subtotal_local is in the order currency; subtotal_usd is converted at "
        "fx_rate_to_usd, the rate on the order date. Comparing the two shows currency effects."
    ),
    "order_items": "Order lines with quantity, discount and line total in USD.",
    "marketing_spend": "Monthly campaign spend by region and channel, with attributed revenue.",
}

DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS regions (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        code TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS currencies (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        symbol TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS countries (
        id INTEGER PRIMARY KEY,
        region_id INTEGER NOT NULL REFERENCES regions(id),
        name TEXT NOT NULL,
        iso_code TEXT NOT NULL UNIQUE,
        currency_code TEXT NOT NULL REFERENCES currencies(code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_lines (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        gross_margin_pct REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        product_line_id INTEGER NOT NULL REFERENCES product_lines(id),
        name TEXT NOT NULL,
        sku TEXT NOT NULL UNIQUE,
        unit_price_usd REAL NOT NULL,
        unit_cost_usd REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        country_id INTEGER NOT NULL REFERENCES countries(id),
        segment TEXT NOT NULL,
        signed_on TEXT NOT NULL,
        churned_on TEXT,
        annual_contract_usd REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        order_date TEXT NOT NULL,
        currency_code TEXT NOT NULL REFERENCES currencies(code),
        fx_rate_to_usd REAL NOT NULL,
        subtotal_local REAL NOT NULL,
        subtotal_usd REAL NOT NULL,
        status TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL,
        unit_price_usd REAL NOT NULL,
        discount_pct REAL NOT NULL,
        line_total_usd REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS marketing_spend (
        id INTEGER PRIMARY KEY,
        region_id INTEGER NOT NULL REFERENCES regions(id),
        campaign TEXT NOT NULL,
        channel TEXT NOT NULL,
        month TEXT NOT NULL,
        spend_usd REAL NOT NULL,
        attributed_revenue_usd REAL NOT NULL
    )
    """,
    # Indexes follow the queries the agent actually issues. Revenue questions filter orders by
    # date and group by region via customers->countries, so those are the two paths indexed.
    "CREATE INDEX IF NOT EXISTS ix_orders_date ON orders(order_date)",
    "CREATE INDEX IF NOT EXISTS ix_orders_customer ON orders(customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_items_order ON order_items(order_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_items_product ON order_items(product_id)",
    "CREATE INDEX IF NOT EXISTS ix_customers_country ON customers(country_id)",
    "CREATE INDEX IF NOT EXISTS ix_countries_region ON countries(region_id)",
    "CREATE INDEX IF NOT EXISTS ix_marketing_region_month ON marketing_spend(region_id, month)",
)


def schema_description() -> str:
    """A compact schema summary for the planner prompt.

    Rendered as text rather than JSON because it goes into a prompt, where every token of
    punctuation is wasted budget.
    """
    lines: list[str] = []
    for table, columns in TABLE_COLUMNS.items():
        description = TABLE_DESCRIPTIONS.get(table, "")
        lines.append(f"{table}({', '.join(columns)})")
        if description:
            lines.append(f"  {description}")
    return "\n".join(lines)
