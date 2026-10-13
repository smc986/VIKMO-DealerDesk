
import csv
import math
import statistics
from pathlib import Path
from collections import defaultdict

from .models import Product

BASE_DIR = Path(__file__).resolve().parent.parent
FORECAST_FILE = BASE_DIR / "ml" / "forecast.csv"
SALES_FILE = BASE_DIR / "data" / "sales_history.csv"
LEAD_TIMES_FILE = BASE_DIR / "data" / "lead_times.csv"


def read_csv(path):
    with open(path, "r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def get_forecast(sku):
    rows = read_csv(FORECAST_FILE)
    results = [
        {
            "sku": row["sku"],
            "week_start": row["week_start"],
            "forecast_units": int(row["forecast_units"]),
        }
        for row in rows
        if row["sku"].upper() == sku.upper()
    ]

    if not results:
        return None

    results.sort(key=lambda item: item["week_start"])
    return results


def get_reorder_data(product):
    sku = product.sku

    lead_rows = read_csv(LEAD_TIMES_FILE)
    lead_time = next(
        (
            int(row["lead_time_weeks"])
            for row in lead_rows
            if row["sku"].upper() == sku.upper()
        ),
        1,
    )

    forecasts = get_forecast(sku) or []
    lead_time_demand = sum(
        row["forecast_units"] for row in forecasts[:lead_time]
    )

    sales_by_sku = defaultdict(list)
    for row in read_csv(SALES_FILE):
        sales_by_sku[row["sku"]].append(
            (row["week_start"], int(float(row["units_sold"])))
        )

    history = sorted(sales_by_sku.get(sku, []))[-12:]
    recent_units = [units for _, units in history]

    sigma = statistics.stdev(recent_units) if len(recent_units) >= 2 else 0
    safety_stock = math.ceil(1.65 * sigma * math.sqrt(lead_time))

    reorder_point = lead_time_demand + safety_stock
    reorder_qty = max(0, math.ceil(reorder_point - product.stock))

    return {
        "sku": sku,
        "name": product.name,
        "current_stock": product.stock,
        "lead_time_weeks": lead_time,
        "lead_time_demand": lead_time_demand,
        "demand_stddev": round(sigma, 2),
        "safety_stock": safety_stock,
        "reorder_point": reorder_point,
        "reorder_qty": reorder_qty,
    }


def get_all_reorder_suggestions():
    suggestions = []

    for product in Product.objects.all().order_by("sku"):
        data = get_reorder_data(product)
        if data["reorder_qty"] > 0:
            suggestions.append(data)

    return suggestions
