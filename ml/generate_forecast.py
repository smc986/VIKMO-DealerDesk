
import csv
import math
from pathlib import Path
from collections import defaultdict
from datetime import date

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "ml"
OUTPUT_FILE = OUTPUT_DIR / "forecast.csv"

FORECAST_WEEKS = [
    "2026-09-28",
    "2026-10-05",
    "2026-10-12",
    "2026-10-19",
]

# Read sales history
sales = defaultdict(list)

with open(
    DATA_DIR / "sales_history.csv",
    "r",
    newline="",
    encoding="utf-8-sig",
) as file:
    reader = csv.DictReader(file)

    for row in reader:
        sku = row["sku"].strip()
        units = int(float(row["units_sold"]))
        sales[sku].append((row["week_start"], units))

# Sort sales by week and calculate recent average
forecast_values = {}

with open(
    DATA_DIR / "lead_times.csv",
    "r",
    newline="",
    encoding="utf-8-sig",
) as file:
    reader = csv.DictReader(file)

    for row in reader:
        sku = row["sku"].strip()
        history = sorted(sales.get(sku, []))

        recent_sales = [units for _, units in history[-8:]]

        if recent_sales:
            forecast_units = math.ceil(
                sum(recent_sales) / len(recent_sales)
            )
        else:
            forecast_units = 0

        forecast_values[sku] = max(0, forecast_units)

# Write 4 weekly forecasts for each SKU
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

with open(
    OUTPUT_FILE,
    "w",
    newline="",
    encoding="utf-8",
) as file:
    writer = csv.DictWriter(
        file,
        fieldnames=["sku", "week_start", "forecast_units"],
    )
    writer.writeheader()

    for sku in sorted(forecast_values):
        for week in FORECAST_WEEKS:
            writer.writerow({
                "sku": sku,
                "week_start": week,
                "forecast_units": forecast_values[sku],
            })

print(f"Forecast saved to: {OUTPUT_FILE}")
print(f"SKUs forecast: {len(forecast_values)}")
print(f"Forecast rows: {len(forecast_values) * len(FORECAST_WEEKS)}")
