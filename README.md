
# VIKMO DealerDesk

An AI-powered dealer management and inventory planning backend built with Django REST Framework and PostgreSQL. The application supports product catalogue search, inventory updates, dealer management, draft order creation, demand forecasting, reorder recommendations, and an AI assistant for dealer operations.

## Features

- **Product catalogue:** Search and filter products by SKU, name, brand, category, and vehicle fitment.
- **Inventory management:** Update stock quantities with validation and inventory change records.
- **Dealer management:** Retrieve dealer information and create dealer records.
- **Order management:** Create and retrieve draft orders with order items, current catalogue prices, and calculated totals.
- **AI dealer assistant:** Uses an LLM with backend tools to search parts, check stock, and create draft orders.
- **Demand forecasting:** Generates four weekly demand forecasts for supported SKUs using historical sales data.
- **Reorder recommendations:** Calculates lead-time demand, safety stock, reorder points, and suggested reorder quantities.
- **Database seeding:** Loads catalogue and dealer data into PostgreSQL using a Django management command.

## Technology Stack

- Python
- Django
- Django REST Framework
- PostgreSQL
- Pandas for CSV-based forecasting
- Groq API with an OpenAI-compatible client for the AI assistant
- CSV files for catalogue, dealer, sales history, lead times, and calendar data

## Project Structure

```text
starter/
├── core/
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── assistant.py
│   ├── forecasting.py
│   └── management/
├── dealerdesk/
│   └── settings.py
├── data/
│   ├── catalogue.csv
│   ├── dealers.csv
│   ├── sales_history.csv
│   ├── lead_times.csv
│   ├── festival_calendar.csv
│   └── promo_calendar.csv
├── ml/
│   ├── generate_forecast.py
│   └── forecast.csv
├── manage.py
├── requirements.txt
├── .env.example
└── README.md
```

## Prerequisites

- Python 3.11 or later
- PostgreSQL
- pip
- A Groq API key to use the AI assistant

## Setup

### 1. Configure the environment

Create a `.env` file from the provided example:

```powershell
Copy-Item .env.example .env
```

Open `.env` and configure the PostgreSQL `DATABASE_URL` and the required AI provider settings.

Keep your actual API keys and database credentials private. Never commit `.env` to Git.

### 2. Install dependencies

From the project root, run:

```powershell
python -m pip install -r requirements.txt
```

### 3. Apply database migrations

```powershell
python manage.py migrate
```

### 4. Load initial data

```powershell
python manage.py seed_data
```

The seed command should be safe to run repeatedly without creating duplicate catalogue products or dealers.

### 5. Generate the forecast data

If the generated forecast file is missing or needs to be refreshed, run:

```powershell
python ml/generate_forecast.py
```

Confirm that `ml/forecast.csv` is generated successfully.

### 6. Start the development server

```powershell
python manage.py runserver
```

The application will be available at:

`http://127.0.0.1:8000/`

## API Endpoints

Base URL: `http://127.0.0.1:8000/api/`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health/` | Health check |
| GET | `/api/products/` | List products |
| GET | `/api/products/?search=filter` | Search products |
| GET | `/api/products/?category=Filters` | Filter by category |
| GET | `/api/products/?vehicle=TVS` | Filter by vehicle fitment |
| POST | `/api/products/` | Create a product |
| GET | `/api/products/<sku>/` | Retrieve a product |
| PATCH | `/api/products/<sku>/` | Update a product |
| PUT | `/api/inventory/<sku>/` | Update stock quantity |
| GET | `/api/dealers/` | List dealers |
| POST | `/api/dealers/` | Create a dealer |
| GET | `/api/dealers/<id>/` | Retrieve a dealer |
| GET | `/api/orders/` | List orders |
| POST | `/api/orders/` | Create a draft order |
| GET | `/api/orders/<id>/` | Retrieve an order |
| POST | `/api/assistant/chat/` | Chat with the AI dealer assistant |
| GET | `/api/forecast/<sku>/` | Retrieve demand forecasts and reorder information |
| GET | `/api/reorder-suggestions/` | Retrieve products requiring reorder |

Pagination is enabled for product and dealer lists, and the orders list uses pagination as well.

## Example Requests

### Health check

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/health/"
```

### Search for a product

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/products/?search=filter"
```

### Update inventory

```powershell
$body = @{
    quantity = 50
    reason = "Stock adjustment"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Put `
    -Uri "http://127.0.0.1:8000/api/inventory/FIL-1016/" `
    -ContentType "application/json" `
    -Body $body
```

### Create a draft order

```powershell
$body = @{
    dealer_id = 1
    items = @(
        @{
            sku = "FIL-1016"
            quantity = 2
        },
        @{
            sku = "BRK-1090"
            quantity = 1
        }
    )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/orders/" `
    -ContentType "application/json" `
    -Body $body
```

### Request a forecast

```powershell
Invoke-RestMethod `
    "http://127.0.0.1:8000/api/forecast/FIL-1016/" |
    ConvertTo-Json -Depth 5
```

### Request reorder suggestions

```powershell
Invoke-RestMethod `
    "http://127.0.0.1:8000/api/reorder-suggestions/" |
    ConvertTo-Json -Depth 5
```

### Use the AI assistant

```powershell
$body = @{
    message = "Find FIL-1016 and check its available stock."
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/assistant/chat/" `
    -ContentType "application/json" `
    -Body $body |
    ConvertTo-Json -Depth 8
```

## Forecasting and Reorder Logic

The forecasting script reads historical sales data and generates weekly forecasts for supported products.

The current baseline forecast uses the average of recent sales observations, rounded up to a whole unit. The generated forecast file is used by the forecast and reorder APIs.

Reorder calculations use:

- Forecast demand during supplier lead time
- Historical demand variability
- Safety stock based on a 1.65 service factor
- Current product stock
- The resulting reorder point and suggested reorder quantity

These calculations provide a baseline inventory planning approach, not a guarantee of future demand.

## AI Assistant

The assistant uses an LLM to interpret dealer requests and invoke backend tools where appropriate.

Supported operations include:

- Searching the product catalogue
- Checking current stock and catalogue prices
- Creating draft orders for specified dealers and products

The response includes the assistant reply, cited SKUs, tool calls, and any actions performed.

The assistant requires a valid configured provider API key. Do not expose API keys in source code, logs, screenshots, or version control.

## Validation and Testing

Run Django's system checks:

```powershell
python manage.py check
```

Run the project's automated tests, if available:

```powershell
python manage.py test
```

Verify the health endpoint and the main product, inventory, dealer, order, forecast, reorder, and assistant APIs.

Before final submission, run the supplied assignment smoke test if `smoke_test.py` is included:

```powershell
python smoke_test.py --base-url http://localhost:8000 --track django
```

Use the track required by your assignment instructions.

## Important Notes

- Draft orders are created with status `DRAFT`.
- Draft order creation does not confirm or dispatch an order.
- Inventory is updated through the inventory endpoint; draft order creation does not automatically deduct stock.
- The current order implementation sets tax to zero. Add tax calculations if required by the assignment specification.
- Forecasts depend on the supplied historical data and the generated forecast file.
- The database must be PostgreSQL, as configured by the project settings.

## Security

- Keep `.env` out of version control.
- Commit `.env.example` with placeholder values only.
- Never include real API keys, passwords, or database credentials in the repository.
- Do not commit virtual environments or generated cache files.

## License

Created as part of the VIKMO DealerDesk assignment.
