from __future__ import annotations

import contextlib
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import TypedDict

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from otto_client import OttoClient


class CartItem(TypedDict):
    product_id: str
    name: str
    quantity: int
    unit_price: float
    currency: str
    line_total: float


@dataclass
class AppContext:
    otto_client: OttoClient
    carts: dict[str, list[CartItem]]


@contextlib.asynccontextmanager
async def app_lifespan(_server: FastMCP):
    yield AppContext(
        otto_client=OttoClient(),
        carts=defaultdict(list),
    )


mcp = FastMCP(
    "otto-mcp",
    instructions="Search Otto-style product data, inspect product details, and manage a session-scoped shopping cart.",
    json_response=True,
    lifespan=app_lifespan,
)


def _session_key(ctx: Context[ServerSession, AppContext]) -> str:
    return getattr(ctx, "client_id", None) or str(id(ctx.session))


def _get_cart(ctx: Context[ServerSession, AppContext]) -> list[CartItem]:
    session_key = _session_key(ctx)
    return ctx.request_context.lifespan_context.carts[session_key]


def _cart_summary(cart: list[CartItem]) -> dict[str, object]:
    total_items = sum(item["quantity"] for item in cart)
    total_amount = round(sum(item["line_total"] for item in cart), 2)
    currency = cart[0]["currency"] if cart else "EUR"
    return {
        "items": cart,
        "total_items": total_items,
        "total_amount": total_amount,
        "currency": currency,
    }


@mcp.tool()
async def search_products(
    query: str,
    limit: int = 10,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> dict[str, object]:
    """Search the Otto product catalog by keyword.

    Args:
        query: Search term for names, descriptions, merchants, or categories.
        limit: Maximum number of products to return.
    """

    if ctx is None:
        raise RuntimeError("MCP context is required for this tool")

    results = await ctx.request_context.lifespan_context.otto_client.search_products(query=query, limit=max(1, min(limit, 25)))
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "data_source": "awin" if ctx.request_context.lifespan_context.otto_client.feed_url else "mock",
    }


@mcp.tool()
async def get_product_details(
    product_id: str,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> dict[str, object]:
    """Get detailed information for a specific product.

    Args:
        product_id: Product identifier from search results.
    """

    if ctx is None:
        raise RuntimeError("MCP context is required for this tool")

    product = await ctx.request_context.lifespan_context.otto_client.get_product_details(product_id)
    if product is None:
        return {"found": False, "product_id": product_id}
    return {"found": True, "product": product}


@mcp.tool()
async def add_to_cart(
    product_id: str,
    quantity: int = 1,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> dict[str, object]:
    """Add a product to the current session's in-memory cart.

    Args:
        product_id: Product identifier to add.
        quantity: Number of units to add.
    """

    if ctx is None:
        raise RuntimeError("MCP context is required for this tool")

    quantity = max(1, quantity)
    product = await ctx.request_context.lifespan_context.otto_client.get_product_details(product_id)
    if product is None:
        return {"added": False, "reason": "Product not found", "product_id": product_id}

    cart = _get_cart(ctx)
    for item in cart:
        if item["product_id"] == product_id:
            item["quantity"] += quantity
            item["line_total"] = round(item["quantity"] * item["unit_price"], 2)
            return {"added": True, "cart": _cart_summary(cart)}

    cart.append(
        {
            "product_id": product_id,
            "name": str(product["name"]),
            "quantity": quantity,
            "unit_price": float(product["price"]),
            "currency": str(product["currency"]),
            "line_total": round(float(product["price"]) * quantity, 2),
        }
    )
    return {"added": True, "cart": _cart_summary(cart)}


@mcp.tool()
async def view_cart(ctx: Context[ServerSession, AppContext] | None = None) -> dict[str, object]:
    """View the current session's cart contents."""

    if ctx is None:
        raise RuntimeError("MCP context is required for this tool")

    return _cart_summary(_get_cart(ctx))


@mcp.tool()
async def remove_from_cart(
    product_id: str,
    quantity: int = 1,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> dict[str, object]:
    """Remove quantity of a product from the current session's cart.

    Args:
        product_id: Product identifier to remove.
        quantity: Number of units to remove. If it reaches zero, the line is removed.
    """

    if ctx is None:
        raise RuntimeError("MCP context is required for this tool")

    quantity = max(1, quantity)
    cart = _get_cart(ctx)
    for index, item in enumerate(cart):
        if item["product_id"] != product_id:
            continue

        item["quantity"] -= quantity
        if item["quantity"] <= 0:
            cart.pop(index)
        else:
            item["line_total"] = round(item["quantity"] * item["unit_price"], 2)

        return {"removed": True, "cart": _cart_summary(cart)}

    return {"removed": False, "reason": "Product not in cart", "product_id": product_id, "cart": _cart_summary(cart)}


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    async with mcp.session_manager.run():
        yield


async def healthcheck(_request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "otto-mcp",
            "transport": "streamable-http",
            "port": int(os.getenv("PORT", "8080")),
            "feed_configured": bool(os.getenv("AWIN_FEED_URL")),
            "mcp_endpoint": "/mcp",
        }
    )


starlette_app = Starlette(
    routes=[
        Route("/", healthcheck),
        Mount("/mcp", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

app = CORSMiddleware(
    starlette_app,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()