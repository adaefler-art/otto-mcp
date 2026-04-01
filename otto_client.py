from __future__ import annotations

import csv
import io
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

import httpx


@dataclass(slots=True)
class Product:
    product_id: str
    name: str
    description: str
    price: float
    currency: str
    category: str
    product_url: str
    image_url: str
    merchant: str
    availability: str = "in_stock"

    def to_dict(self) -> dict[str, str | float]:
        return asdict(self)


MOCK_PRODUCTS: list[Product] = [
    Product(
        product_id="mock-otto-001",
        name="Otto Lounge Chair",
        description="Curved lounge chair with textured upholstery and oak legs.",
        price=249.99,
        currency="EUR",
        category="Furniture",
        product_url="https://example.com/products/mock-otto-001",
        image_url="https://images.example.com/mock-otto-001.jpg",
        merchant="Otto Mock Store",
    ),
    Product(
        product_id="mock-otto-002",
        name="Otto Desk Lamp",
        description="Matte steel desk lamp with dimmable warm LED lighting.",
        price=59.95,
        currency="EUR",
        category="Lighting",
        product_url="https://example.com/products/mock-otto-002",
        image_url="https://images.example.com/mock-otto-002.jpg",
        merchant="Otto Mock Store",
    ),
    Product(
        product_id="mock-otto-003",
        name="Otto Cotton Throw",
        description="Soft woven cotton throw blanket in sand and graphite tones.",
        price=39.5,
        currency="EUR",
        category="Home",
        product_url="https://example.com/products/mock-otto-003",
        image_url="https://images.example.com/mock-otto-003.jpg",
        merchant="Otto Mock Store",
    ),
    Product(
        product_id="mock-otto-004",
        name="Otto Runner Sneakers",
        description="Lightweight everyday sneakers with breathable knit upper.",
        price=89.0,
        currency="EUR",
        category="Footwear",
        product_url="https://example.com/products/mock-otto-004",
        image_url="https://images.example.com/mock-otto-004.jpg",
        merchant="Otto Mock Store",
    ),
]


class OttoClient:
    def __init__(self, feed_url: str | None = None, cache_ttl_seconds: int = 300) -> None:
        self.feed_url = feed_url or os.getenv("AWIN_FEED_URL")
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_products: list[Product] | None = None
        self._cache_expiry = 0.0

    async def load_products(self, force_refresh: bool = False) -> list[Product]:
        now = time.time()
        if (
            not force_refresh
            and self._cached_products is not None
            and now < self._cache_expiry
        ):
            return self._cached_products

        if not self.feed_url:
            products = list(MOCK_PRODUCTS)
        else:
            products = await self._fetch_feed_products(self.feed_url)
            if not products:
                products = list(MOCK_PRODUCTS)

        self._cached_products = products
        self._cache_expiry = now + self.cache_ttl_seconds
        return products

    async def search_products(self, query: str, limit: int = 10) -> list[dict[str, str | float]]:
        normalized_query = query.strip().lower()
        products = await self.load_products()

        if not normalized_query:
            matches = products[:limit]
        else:
            scored: list[tuple[int, Product]] = []
            for product in products:
                haystack = " ".join(
                    [
                        product.name,
                        product.description,
                        product.category,
                        product.merchant,
                    ]
                ).lower()
                if normalized_query in haystack:
                    score = 0
                    if normalized_query in product.name.lower():
                        score += 3
                    if normalized_query in product.category.lower():
                        score += 2
                    if normalized_query in product.description.lower():
                        score += 1
                    scored.append((score, product))

            matches = [product for _, product in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]

        return [product.to_dict() for product in matches]

    async def get_product_details(self, product_id: str) -> dict[str, str | float] | None:
        products = await self.load_products()
        for product in products:
            if product.product_id == product_id:
                return product.to_dict()
        return None

    async def _fetch_feed_products(self, feed_url: str) -> list[Product]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(feed_url)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        text = response.text.strip()
        if not text:
            return []

        if "xml" in content_type or text.startswith("<") or feed_url.lower().endswith(".xml"):
            return self._parse_xml_feed(text)
        return self._parse_csv_feed(text)

    def _parse_csv_feed(self, content: str) -> list[Product]:
        reader = csv.DictReader(io.StringIO(content))
        products: list[Product] = []
        for row in reader:
            product = self._product_from_mapping(row)
            if product is not None:
                products.append(product)
        return products

    def _parse_xml_feed(self, content: str) -> list[Product]:
        root = ET.fromstring(content)
        products: list[Product] = []
        product_nodes = root.findall(".//product") or root.findall(".//item") or list(root)

        for node in product_nodes:
            row = {self._clean_tag(child.tag): (child.text or "") for child in list(node)}
            product = self._product_from_mapping(row)
            if product is not None:
                products.append(product)

        return products

    def _product_from_mapping(self, raw: dict[str, str]) -> Product | None:
        normalized = {self._normalize_key(key): (value or "").strip() for key, value in raw.items() if key}

        product_id = self._first_value(
            normalized,
            "product_id",
            "merchant_product_id",
            "id",
            "aw_product_id",
            "sku",
        )
        name = self._first_value(normalized, "name", "product_name", "title")
        if not product_id or not name:
            return None

        description = self._first_value(normalized, "description", "product_description", "summary")
        category = self._first_value(normalized, "category", "merchant_category", "store_category", default="General")
        product_url = self._first_value(normalized, "product_url", "aw_deep_link", "deeplink", "link")
        image_url = self._first_value(normalized, "image_url", "merchant_image_url", "image", "image_link")
        merchant = self._first_value(normalized, "merchant", "merchant_name", "brand_name", default="AWIN Merchant")
        currency = self._first_value(normalized, "currency", "currency_code", default="EUR")
        availability = self._first_value(normalized, "availability", "in_stock", default="in_stock")
        price = self._parse_price(
            self._first_value(normalized, "price", "search_price", "store_price", "sale_price", default="0")
        )

        return Product(
            product_id=product_id,
            name=name,
            description=description,
            price=price,
            currency=currency,
            category=category,
            product_url=product_url,
            image_url=image_url,
            merchant=merchant,
            availability=availability,
        )

    @staticmethod
    def _normalize_key(value: str) -> str:
        return value.strip().lower().replace(":", "_").replace("-", "_").replace(" ", "_")

    @staticmethod
    def _clean_tag(tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", maxsplit=1)[-1]
        return tag

    @staticmethod
    def _first_value(mapping: dict[str, str], *keys: str, default: str = "") -> str:
        for key in keys:
            value = mapping.get(key)
            if value:
                return value
        return default

    @staticmethod
    def _parse_price(raw_value: str) -> float:
        cleaned = raw_value.replace("EUR", "").replace("USD", "").replace(",", ".").strip()
        numeric = "".join(character for character in cleaned if character.isdigit() or character == ".")
        try:
            return round(float(numeric), 2)
        except ValueError:
            return 0.0