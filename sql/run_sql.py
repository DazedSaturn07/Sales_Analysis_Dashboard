"""Optional MySQL loading and the independent SQL comparisons used by notebook 03."""

import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/online_retail_II.csv"
PROCESSED = ROOT / "data/processed"
QUALITY = ROOT / "data/quality"
TABLES = ROOT / "power_bi/tables"
SOURCE_COLUMNS = [
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "CustomerID",
    "Country",
]
FACT_COLUMNS = [
    "SourceRow",
    *SOURCE_COLUMNS,
    "InvoiceDay",
    "RevenuePence",
    "TotalAmount",
    "Year",
    "Month",
    "MonthName",
    "DayOfWeek",
    "WeekdayNumber",
    "Hour",
]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def read_fact() -> pd.DataFrame:
    return pd.read_csv(
        PROCESSED / "cleaned_retail.csv",
        dtype={"Invoice": "string", "StockCode": "string", "CustomerID": "string"},
        parse_dates=["InvoiceDate"],
    )


def kpis(fact: pd.DataFrame) -> dict:
    orders = fact.Invoice.nunique()
    revenue = int(fact.RevenuePence.sum())
    frequencies = fact.groupby("CustomerID").Invoice.nunique()
    return {
        "sales_lines": len(fact),
        "revenue_pence": revenue,
        "revenue_gbp": revenue / 100,
        "orders": orders,
        "customers": fact.CustomerID.nunique(),
        "products": fact.StockCode.nunique(),
        "countries": fact.Country.nunique(),
        "quantity": int(fact.Quantity.sum()),
        "average_order_value_gbp": revenue / 100 / orders,
        "repeat_customers": int(frequencies.gt(1).sum()),
        "repeat_customer_rate": float(frequencies.gt(1).mean()),
        "first_date": fact.InvoiceDay.min(),
        "last_date": fact.InvoiceDay.max(),
        "currency": "GBP",
    }


def load_tables():
    """Read the Python handoffs created by notebook 02, preserving identifier text."""
    tables = {}
    for name in [
        "orders",
        "customer_metrics",
        "calendar",
        "monthly_revenue",
        "country_revenue",
        "product_performance",
        "daily_revenue",
        "hourly_revenue",
        "rfm_segments",
        "cohort_retention",
    ]:
        folder = (
            PROCESSED if name in {"orders", "customer_metrics", "calendar"} else TABLES
        )
        tables[name] = pd.read_csv(
            folder / f"{name}.csv",
            dtype={"Invoice": "string", "StockCode": "string", "CustomerID": "string"},
        )
    tables["calendar"]["Date"] = pd.to_datetime(tables["calendar"].Date)
    return tables


def queries() -> dict[str, str]:
    text = (ROOT / "sql/02_analysis.sql").read_text(encoding="utf-8")
    pieces = re.split(r"-- name: (\w+)\s*\n", text)
    return {
        pieces[i]: pieces[i + 1].strip().rstrip(";") for i in range(1, len(pieces), 2)
    }


def sqlite_results(
    fact: pd.DataFrame, path: Path | None = None
) -> dict[str, pd.DataFrame]:
    # Build and validate in a temporary sibling; replace only after all SELECTs pass.
    temporary = path.with_suffix(".building.sqlite") if path else None
    if temporary:
        temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(
            sqlite3.connect(str(temporary) if temporary else ":memory:")
        ) as connection:
            connection.create_function(
                "DATEDIFF",
                2,
                lambda a, b: (date.fromisoformat(a) - date.fromisoformat(b)).days,
            )
            data = fact[FACT_COLUMNS].copy()
            data["InvoiceDate"] = data.InvoiceDate.dt.strftime("%Y-%m-%d %H:%M:%S")
            data.to_sql(
                "sales", connection, if_exists="replace", index=False, chunksize=10000
            )
            connection.execute("CREATE UNIQUE INDEX idx_source ON sales(SourceRow)")
            connection.execute("CREATE INDEX idx_invoice ON sales(Invoice)")
            connection.execute("CREATE INDEX idx_customer ON sales(CustomerID)")
            results = {
                name: pd.read_sql_query(query, connection)
                for name, query in queries().items()
            }
            connection.commit()
        if path:
            temporary.replace(path)
        return results
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def compare_sql(
    results: dict[str, pd.DataFrame], fact: pd.DataFrame, tables: dict
) -> list[dict]:
    checks = []

    def exact(name, left, right, keys, columns):
        l = left[keys + columns].copy().sort_values(keys).reset_index(drop=True)
        r = right[keys + columns].copy().sort_values(keys).reset_index(drop=True)
        for key in keys:
            l[key], r[key] = l[key].astype(str), r[key].astype(str)
        # Sort again after type conversion: IDs must be compared as identifiers.
        l, r = (
            l.sort_values(keys).reset_index(drop=True),
            r.sort_values(keys).reset_index(drop=True),
        )
        pd.testing.assert_frame_equal(l, r, check_dtype=False, check_exact=True)
        checks.append({"check": name, "rows": len(l), "passed": True})

    metrics = kpis(fact)
    expected = pd.DataFrame(
        [
            {
                key: metrics[value]
                for key, value in {
                    "SalesLines": "sales_lines",
                    "RevenuePence": "revenue_pence",
                    "Orders": "orders",
                    "Customers": "customers",
                    "Products": "products",
                    "Countries": "countries",
                    "Quantity": "quantity",
                }.items()
            }
        ]
    )
    for col in expected:
        if int(results["kpis"][col].iloc[0]) != int(expected[col].iloc[0]):
            raise AssertionError(f"SQL KPI mismatch: {col}")
        checks.append({"check": f"kpi_{col}", "rows": 1, "passed": True})
    if (
        abs(
            float(results["kpis"].AvgOrderValue.iloc[0])
            - metrics["average_order_value_gbp"]
        )
        > 0.000001
    ):
        raise AssertionError("SQL average order value mismatch")
    checks.append({"check": "kpi_AvgOrderValue", "rows": 1, "passed": True})
    month = tables["monthly_revenue"].copy()
    month["Year"] = pd.to_datetime(month.MonthStart).dt.year
    month["Month"] = pd.to_datetime(month.MonthStart).dt.month
    exact(
        "monthly_revenue",
        results["monthly_revenue"],
        month,
        ["Year", "Month"],
        ["RevenuePence", "Orders", "Customers"],
    )
    for name, keys, columns in [
        ("country_revenue", ["Country"], ["RevenuePence", "Orders", "Customers"]),
        ("product_performance", ["StockCode"], ["RevenuePence", "Quantity", "Orders"]),
        ("daily_revenue", ["WeekdayNumber", "DayOfWeek"], ["RevenuePence", "Orders"]),
        ("hourly_revenue", ["Hour"], ["RevenuePence", "Orders"]),
        ("orders", ["Invoice"], ["RevenuePence", "Quantity", "Lines", "CustomerID"]),
        (
            "customer_metrics",
            ["CustomerID"],
            [
                "Recency",
                "Frequency",
                "MonetaryPence",
                "R_Score",
                "F_Score",
                "M_Score",
                "Segment",
            ],
        ),
    ]:
        exact(name, results[name], tables[name], keys, columns)
    cohort = tables["cohort_retention"].copy()
    for column, output in [
        ("CohortMonth", "CohortKey"),
        ("ActivityMonth", "ActivityKey"),
    ]:
        dates = pd.to_datetime(cohort[column])
        cohort[output] = dates.dt.year * 12 + dates.dt.month
    exact(
        "cohort_retention",
        results["cohort_retention"],
        cohort,
        ["CohortKey", "ActivityKey"],
        ["MonthIndex", "ActiveCustomers", "CohortSize"],
    )
    return checks


def normalize(frame):
    frame = frame[FACT_COLUMNS].sort_values("SourceRow").reset_index(drop=True).copy()
    frame["InvoiceDate"] = pd.to_datetime(frame.InvoiceDate)
    frame["InvoiceDay"] = frame.InvoiceDay.astype(str)
    for col in ["Price", "TotalAmount"]:
        frame[col] = frame[col].astype(float)
    for col in [
        "Invoice",
        "StockCode",
        "CustomerID",
        "Description",
        "Country",
        "MonthName",
        "DayOfWeek",
    ]:
        frame[col] = frame[col].astype(str)
    return frame


def fetch_frame(cursor, query):
    cursor.execute(query)
    return pd.DataFrame(cursor.fetchall(), columns=[c[0] for c in cursor.description])


def run(host, port, user, password, database, replace_sales=False):
    import mysql.connector

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", database):
        raise ValueError(
            "Database name must contain only letters, numbers and underscores."
        )
    fact = read_fact()
    expected = normalize(fact)
    stage = "sales_incoming_" + uuid.uuid4().hex[:12]
    connection = mysql.connector.connect(
        host=host, port=port, user=user, password=password, connection_timeout=10
    )
    cursor = connection.cursor()
    stage_exists = False
    try:
        cursor.execute("SET SESSION lock_wait_timeout = 10")
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4"
        )
        cursor.execute(f"USE `{database}`")
        cursor.execute("SHOW TABLES LIKE 'sales'")
        exists = bool(cursor.fetchone())
        same = False
        if exists:
            actual = normalize(
                fetch_frame(cursor, "SELECT * FROM sales ORDER BY SourceRow")
            )
            try:
                pd.testing.assert_frame_equal(
                    actual, expected, check_dtype=False, check_exact=True
                )
                same = True
            except AssertionError:
                if not replace_sales:
                    raise RuntimeError(
                        "Existing sales differ from this source. Inspect them; use --replace-sales only for an intentional rebuild."
                    )
        if not same:
            schema = (ROOT / "sql/01_schema_mysql.sql").read_text(encoding="utf-8")
            cursor.execute(re.sub(r"\bsales\b", stage, schema).rstrip().rstrip(";"))
            stage_exists = True
            data = fact[FACT_COLUMNS].copy()
            data.InvoiceDate = data.InvoiceDate.dt.strftime("%Y-%m-%d %H:%M:%S")
            placeholders = ",".join(["%s"] * len(FACT_COLUMNS))
            insert = f"INSERT INTO `{stage}` ({','.join('`' + c + '`' for c in FACT_COLUMNS)}) VALUES ({placeholders})"
            for start in range(0, len(data), 5000):
                cursor.executemany(
                    insert,
                    list(
                        data.iloc[start : start + 5000].itertuples(
                            index=False, name=None
                        )
                    ),
                )
                connection.commit()  # Only the new, private staging table is touched.
            loaded = normalize(
                fetch_frame(cursor, f"SELECT * FROM `{stage}` ORDER BY SourceRow")
            )
            pd.testing.assert_frame_equal(
                loaded, expected, check_dtype=False, check_exact=True
            )
        table = "sales" if same else stage
        results = {
            name: fetch_frame(cursor, re.sub(r"\bsales\b", table, query))
            for name, query in queries().items()
        }
        checks = compare_sql(results, fact, load_tables())
        if not same:
            if exists:
                backup = "sales_previous_" + uuid.uuid4().hex[:12]
                cursor.execute(f"RENAME TABLE sales TO `{backup}`, `{stage}` TO sales")
                # Preserve the prior table for deliberate manual retirement.
                print(f"Previous sales retained as {backup}.")
            else:
                cursor.execute(f"RENAME TABLE `{stage}` TO sales")
            stage_exists = False
        with (ROOT / "data/processed/cleaned_retail.csv").open("rb") as stream:
            fact_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        evidence = {
            "status": "passed",
            "engine": "MySQL",
            "source_rows": len(fact),
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "fact_sha256": fact_hash,
            "exact_full_content_comparison": True,
            "reused_existing": same,
            "checks_passed": len(checks),
            "checks": checks,
        }
        write_json(QUALITY / "mysql_validation.json", evidence)
        print(
            f"MySQL: full-content match and {len(checks)} analytical comparison groups passed; reused={same}."
        )
        return evidence
    finally:
        if stage_exists:
            cursor.execute(f"DROP TABLE IF EXISTS `{stage}`")
        cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", required=True)
    parser.add_argument("--database", default="sales_analytics")
    parser.add_argument(
        "--replace-sales",
        action="store_true",
        help="Intentionally replace differing project sales; retains a backup table",
    )
    args = parser.parse_args()
    password = os.environ.get("MYSQL_PASSWORD")
    if password is None:
        password = getpass.getpass("MySQL password (not saved): ")
    run(args.host, args.port, args.user, password, args.database, args.replace_sales)


if __name__ == "__main__":
    main()
