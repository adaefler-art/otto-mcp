# otto-mcp

`otto-mcp` is a Python MCP server for remote deployment on fly.io. It exposes an Otto-style shopping workflow over MCP using streamable HTTP transport and loads product data from an AWIN feed when `AWIN_FEED_URL` is configured.

## Features

- MCP server over HTTP with streamable responses at `/mcp`
- Session-scoped in-memory cart support
- Tools:
  - `search_products`
  - `get_product_details`
  - `add_to_cart`
  - `view_cart`
  - `remove_from_cart`
- AWIN feed ingestion from `AWIN_FEED_URL`
- CSV and XML feed parsing support
- Mock catalog fallback when no feed URL is configured
- Docker and fly.io deployment configuration

## Requirements

- Python 3.12+
- GitHub CLI authenticated if you want to publish the repository

## Environment Variables

- `AWIN_FEED_URL`: Optional AWIN product feed URL. If omitted, the server uses bundled mock data.
- `PORT`: Optional HTTP port for the server. Defaults to `8080`.

## Local Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
```

The health endpoint will be available at `http://localhost:8080/` and the MCP endpoint at `http://localhost:8080/mcp`.

## Smoke Test Client

Run the local smoke test client against a running server:

```bash
python smoke_test_client.py
```

Optional flags:

```bash
python smoke_test_client.py --url http://localhost:8080/mcp --query lamp --limit 5
```

The smoke test does the following in one session:

- lists available tools
- calls `search_products`
- calls `get_product_details` for the first result, if present
- calls `add_to_cart`
- calls `view_cart`
- calls `remove_from_cart`

This is intended as a quick local verification pass for the deployed or local streamable HTTP endpoint.

## MCP Tool Behavior

### `search_products`

Searches the product catalog by keyword across name, description, merchant, and category.

### `get_product_details`

Returns a full product record by `product_id`.

### `add_to_cart`

Adds a product to the current session cart. Cart state is stored in memory and isolated per MCP session.

### `view_cart`

Returns all current cart items and totals for the current session.

### `remove_from_cart`

Removes quantity from a cart line or deletes the line if the quantity reaches zero.

## Feed Parsing Notes

`otto_client.py` tries to detect whether the feed is CSV or XML by checking the response content type, URL suffix, and payload shape.

It maps common affiliate feed field names such as:

- `product_id`
- `merchant_product_id`
- `product_name`
- `description`
- `search_price`
- `store_price`
- `aw_deep_link`
- `merchant_image_url`

If the AWIN feed schema differs, extend the field mapping in `OttoClient._product_from_mapping`.

## Docker

Build and run locally:

```bash
docker build -t otto-mcp .
docker run -p 8080:8080 -e AWIN_FEED_URL="https://example.com/feed.csv" otto-mcp
```

## Fly.io

Deploy after creating the Fly app:

```bash
fly launch --copy-config --no-deploy
fly secrets set AWIN_FEED_URL="https://example.com/feed.csv"
fly deploy
```

If you want to deploy immediately without a real feed URL, the app still works with mock data and can be deployed without setting `AWIN_FEED_URL`. Once you have the real feed URL, set it with `fly secrets set` and redeploy.

## Publish to GitHub

The requested repo bootstrap commands are:

```bash
git init
git add .
git commit -m "initial commit: otto mcp server"
gh repo create otto-mcp --public --source=. --remote=origin --push
```

## Notes

- The server uses streamable HTTP because it is the recommended production transport in the Python MCP SDK.
- Cart state is intentionally in-memory only. Restarting the process clears carts.