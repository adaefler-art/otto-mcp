from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test the otto-mcp streamable HTTP endpoint.")
    parser.add_argument(
        "--url",
        default="http://localhost:8080/mcp",
        help="Base MCP endpoint URL. Defaults to http://localhost:8080/mcp",
    )
    parser.add_argument(
        "--query",
        default="otto",
        help="Search query to use during the smoke test. Defaults to 'otto'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Maximum number of search results to request. Defaults to 3.",
    )
    return parser.parse_args()


def _print_json(label: str, payload: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))


async def run_smoke_test(url: str, query: str, limit: int) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            _print_json("tools", [tool.name for tool in tools.tools])

            search_result = await session.call_tool(
                "search_products",
                arguments={"query": query, "limit": limit},
            )
            _print_json("search_products", search_result.structuredContent or search_result.model_dump())

            results = []
            if search_result.structuredContent:
                results = list(search_result.structuredContent.get("results", []))

            if results:
                product_id = str(results[0].get("product_id", ""))
                if product_id:
                    details_result = await session.call_tool(
                        "get_product_details",
                        arguments={"product_id": product_id},
                    )
                    _print_json(
                        "get_product_details",
                        details_result.structuredContent or details_result.model_dump(),
                    )

                    add_result = await session.call_tool(
                        "add_to_cart",
                        arguments={"product_id": product_id, "quantity": 1},
                    )
                    _print_json("add_to_cart", add_result.structuredContent or add_result.model_dump())

                    cart_result = await session.call_tool("view_cart", arguments={})
                    _print_json("view_cart", cart_result.structuredContent or cart_result.model_dump())

                    remove_result = await session.call_tool(
                        "remove_from_cart",
                        arguments={"product_id": product_id, "quantity": 1},
                    )
                    _print_json(
                        "remove_from_cart",
                        remove_result.structuredContent or remove_result.model_dump(),
                    )


def main() -> None:
    args = _parse_args()
    asyncio.run(run_smoke_test(url=args.url, query=args.query, limit=args.limit))


if __name__ == "__main__":
    main()