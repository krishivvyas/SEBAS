"""Steam wishlist prices and new Bookswagon light novel listings."""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

import httpx
from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import (
    BROWSER_USER_AGENT,
    SebasTool,
    ToolError,
    http_get_json,
    require_env,
)

_MAX_NAME_LOOKUPS = 15


@ToolRegistry.register("steam_wishlist")
class SteamWishlistTool(SebasTool):
    name = "steam_wishlist"
    description = (
        "Check prices on the user's Steam wishlist and report which games are "
        "discounted, with sale and original prices."
    )
    parameters = {"type": "object", "properties": {}}
    timeout_seconds = 60.0

    def run(self) -> str:
        steam_id = require_env("STEAM_ID", "the Steam wishlist")
        country = os.environ.get("STEAM_COUNTRY", "").strip() or "in"
        data = http_get_json(
            "https://api.steampowered.com/IWishlistService/GetWishlist/v1/",
            params={"steamid": steam_id},
            service="Steam",
        )
        app_ids = [str(item["appid"]) for item in data.get("response", {}).get("items", [])]
        if not app_ids:
            return (
                "The Steam wishlist is empty or private. Wishlists can only be read "
                "when the profile's game details are public."
            )

        prices: dict[str, dict] = {}
        for start in range(0, len(app_ids), 50):
            batch = http_get_json(
                "https://store.steampowered.com/api/appdetails",
                params={
                    "appids": ",".join(app_ids[start : start + 50]),
                    "cc": country,
                    "filters": "price_overview",
                },
                service="the Steam store",
            )
            for app_id, entry in batch.items():
                if entry.get("success") and isinstance(entry.get("data"), dict):
                    if overview := entry["data"].get("price_overview"):
                        prices[app_id] = overview

        on_sale = sorted(
            (a for a, p in prices.items() if p.get("discount_percent")),
            key=lambda a: -prices[a]["discount_percent"],
        )
        lines = [
            f"Wishlist: {len(app_ids)} games, {len(prices)} with a price, "
            f"{len(on_sale)} on sale."
        ]
        for app_id in on_sale[:_MAX_NAME_LOOKUPS]:
            p = prices[app_id]
            lines.append(
                f"- {self._name(app_id)}: {p['final_formatted']} "
                f"(-{p['discount_percent']}%, was {p['initial_formatted']})"
            )
        if len(on_sale) > _MAX_NAME_LOOKUPS:
            lines.append(f"...and {len(on_sale) - _MAX_NAME_LOOKUPS} more on sale.")
        return "\n".join(lines)

    @staticmethod
    def _name(app_id: str) -> str:
        try:
            data = http_get_json(
                "https://store.steampowered.com/api/appdetails",
                params={"appids": app_id, "filters": "basic"},
                service="the Steam store",
            )
            return data[app_id]["data"]["name"]
        except (ToolError, KeyError, TypeError):
            return f"App {app_id}"


_CARD = re.compile(r'<div class="product-card">(.*?)</li>', re.DOTALL)


def parse_bookswagon(page: str) -> list[dict]:
    books = []
    for card in _CARD.findall(page):
        link = re.search(r'href="(https://www\.bookswagon\.com/book/[^"]+/(\d{10,13}))"\s+title="([^"]+)"', card)
        if not link:
            continue
        author = re.search(r'class="book-author">([^<]*)<', card)
        price = re.search(r'class="current-price">([^<]*)<', card)
        books.append(
            {
                "isbn": link.group(2),
                "title": html.unescape(link.group(3)).strip(),
                "author": html.unescape(author.group(1)).strip() if author else "",
                "price": price.group(1).strip() if price else "",
                "url": link.group(1),
            }
        )
    return books


@ToolRegistry.register("bookswagon_new_releases")
class BookswagonNewReleasesTool(SebasTool):
    name = "bookswagon_new_releases"
    description = (
        "Check Bookswagon for light novels that have appeared since the last "
        "check. The first check records the current listings as a baseline."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search terms, e.g. a series name. Default: light novel.",
            }
        },
    }
    timeout_seconds = 45.0

    @staticmethod
    def state_path() -> Path:
        return get_data_dir() / "sebas" / "bookswagon_seen.json"

    def run(self, query: str = "") -> str:
        query = (query or "light novel").strip()
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
        try:
            response = httpx.get(
                f"https://www.bookswagon.com/search-books/{slug}",
                headers={"User-Agent": BROWSER_USER_AGENT},
                timeout=30,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"Could not load Bookswagon: {exc}") from exc

        books = parse_bookswagon(response.text)
        if not books:
            raise ToolError(
                "Bookswagon returned no recognisable listings. Their page layout "
                "may have changed, which would need the scraper updating."
            )

        path = self.state_path()
        state = json.loads(path.read_text("utf-8")) if path.exists() else {}
        seen = set(state.get(slug, []))
        first_check = slug not in state
        new = [b for b in books if b["isbn"] not in seen]
        state[slug] = sorted(seen | {b["isbn"] for b in books})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=1), "utf-8")

        if first_check:
            return (
                f"First check for '{query}': recorded {len(books)} current listings. "
                "Future checks will report only new arrivals."
            )
        if not new:
            return f"No new '{query}' listings on Bookswagon since the last check."
        lines = [f"{len(new)} new '{query}' listings on Bookswagon:"]
        lines += [f"- {b['title']} by {b['author'] or 'unknown'}, {b['price']}" for b in new[:15]]
        return "\n".join(lines)
