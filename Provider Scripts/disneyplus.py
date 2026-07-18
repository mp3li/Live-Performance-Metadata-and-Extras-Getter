#!/usr/bin/env python3
"""
Disney+ detail-page metadata helpers.

Disney+ browse entity pages expose public Next.js page data with structured
hero, details, and metadata blocks. This provider reads that page state instead
of relying only on rendered screen text.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


NAME = "Disney+"
STUDIO_NAME = "Disney+"
PAGE_HOSTS = {"disneyplus.com", "www.disneyplus.com"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


@dataclass
class DisneyPlusMetadata:
    source_url: str = ""
    detail_link: str = ""
    entity_id: str = ""
    title: str = ""
    short_description: str = ""
    long_description: str = ""
    year: str = ""
    runtime_minutes: str = ""
    content_rating: str = ""
    poster_url: str = ""
    wide_url: str = ""
    logo_url: str = ""
    trailer_url: str = ""
    category: str = ""
    genres: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)


def is_disneyplus_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    return parsed.netloc.casefold() in PAGE_HOSTS


def is_supported_url(url: str) -> bool:
    return bool(is_disneyplus_url(url) and entity_id_from_url(url))


def entity_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(clean_text(url))
    match = re.search(r"/browse/entity-([0-9a-f\-]+)", parsed.path, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def extract_metadata(url: str, timeout: int = 25) -> DisneyPlusMetadata:
    entity_id = entity_id_from_url(url)
    if not entity_id:
        raise ValueError("Disney+ links need a /browse/entity-... ID.")

    html_text = fetch_text(url, timeout=timeout)
    next_data = extract_next_data(html_text)
    metadata_block = find_main_content_block(next_data, "Metadata")
    hero_block = find_main_content_block(next_data, "DetailEntityHero")
    details_block = find_main_content_block(next_data, "MediaDetails")
    json_ld = extract_ldjson_movie(metadata_block)

    item = DisneyPlusMetadata(
        source_url=meta_content(metadata_block, "og:url") or canonical_url(html_text) or url,
        detail_link=url,
        entity_id=entity_id,
    )

    item.title = clean_title(
        first_non_empty(
            clean_text(json_ld.get("name")),
            meta_content(metadata_block, "og:title"),
            nested_image_alt(hero_block, "titleVisual"),
            nested_image_alt(hero_block, "backgroundImage"),
        )
    )
    item.short_description = first_non_empty(
        clean_text(json_ld.get("description")),
        meta_content(metadata_block, "description"),
        clean_text(hero_block.get("synopsisText")),
    )
    item.long_description = first_non_empty(
        clean_text(details_block.get("summary")),
        clean_text(hero_block.get("synopsisText")),
        item.short_description,
    )
    item.year = first_non_empty(
        clean_text(hero_block.get("releaseYear")),
        clean_text(json_ld.get("datePublished")),
    )
    item.content_rating = first_non_empty(
        clean_text(json_ld.get("contentRating")),
        first_detail_icon_alt(hero_block),
    )
    item.runtime_minutes = first_non_empty(
        runtime_minutes_from_ms(hero_block.get("runtimeMs")),
        runtime_minutes_from_ms(details_block.get("runtimeMs")),
    )
    item.genres = dedupe_text(
        split_values(hero_block.get("genres"))
        or split_values(details_block.get("genres"))
        or split_values(json_ld.get("genre"))
    )
    item.poster_url = first_non_empty(
        meta_content(metadata_block, "og:image"),
        clean_text(json_ld.get("image")),
    )
    item.wide_url = image_source(hero_block.get("backgroundImage")) or item.poster_url
    item.logo_url = image_source(hero_block.get("titleVisual"))
    item.trailer_url = extract_play_url(html_text)
    item.category = category_text(details_block.get("customField"))
    item.directors, item.cast = credits_from_details(details_block.get("credits"))

    if not item.title:
        raise ValueError("Disney+ page did not expose a usable title.")
    return item


def fetch_text(url: str, timeout: int = 25, max_bytes: int = 80 * 1024 * 1024) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(max_bytes).decode("utf-8", errors="replace")
    except Exception:
        return fetch_text_with_curl(url, timeout=timeout, max_bytes=max_bytes)


def fetch_text_with_curl(url: str, timeout: int, max_bytes: int) -> str:
    command = [
        "/usr/bin/curl",
        "--location",
        "--fail",
        "--silent",
        "--show-error",
        "--compressed",
        "--max-time",
        str(timeout),
        "--max-filesize",
        str(max_bytes),
        "--user-agent",
        USER_AGENT,
        url,
    ]
    result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exited with {result.returncode}")
    return result.stdout


def extract_next_data(html_text: str) -> dict[str, Any]:
    match = re.search(
        r"<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    try:
        data = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def find_main_content_block(data: dict[str, Any], type_name: str) -> dict[str, Any]:
    stitch = nested_value(data, ("props", "pageProps", "stitchDocument", "mainContent"))
    if not isinstance(stitch, list):
        return {}
    for item in stitch:
        if isinstance(item, dict) and clean_text(item.get("_type")) == type_name:
            return item
    return {}


def extract_ldjson_movie(metadata_block: dict[str, Any]) -> dict[str, Any]:
    ld_json = metadata_block.get("ldJSON")
    if not isinstance(ld_json, dict):
        return {}
    graph = ld_json.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            if isinstance(item, dict) and clean_text(item.get("@type")).casefold() == "movie":
                return item
    if clean_text(ld_json.get("@type")).casefold() == "movie":
        return ld_json
    return {}


def meta_content(metadata_block: dict[str, Any], key: str) -> str:
    meta_tags = metadata_block.get("metaTags")
    if not isinstance(meta_tags, list):
        return ""
    wanted = key.casefold()
    for item in meta_tags:
        if not isinstance(item, dict):
            continue
        for attr in ("property", "name", "itemProp"):
            if clean_text(item.get(attr)).casefold() == wanted:
                return clean_text(item.get("content"))
    return ""


def canonical_url(html_text: str) -> str:
    match = re.search(
        r"<link\b[^>]*rel=[\"']canonical[\"'][^>]*href=[\"']([^\"']+)[\"']",
        html_text,
        flags=re.IGNORECASE,
    )
    return clean_text(html.unescape(match.group(1))) if match else ""


def image_source(image_block: Any) -> str:
    if not isinstance(image_block, dict):
        return ""
    for key in ("defaultImage", "largeImage", "xlargeImage", "mediumImage", "smallImage"):
        value = image_block.get(key)
        if isinstance(value, dict) and clean_text(value.get("source")):
            return clean_text(value.get("source"))
    return ""


def nested_image_alt(block: dict[str, Any], key: str) -> str:
    value = block.get(key)
    return clean_text(value.get("alt")) if isinstance(value, dict) else ""


def first_detail_icon_alt(hero_block: dict[str, Any]) -> str:
    icons = hero_block.get("detailIcons")
    if not isinstance(icons, list):
        return ""
    for item in icons:
        alt = clean_text(item.get("alt")) if isinstance(item, dict) else ""
        if re.fullmatch(r"[A-Z0-9\-]+", alt):
            return alt
    return ""


def runtime_minutes_from_ms(value: Any) -> str:
    text = clean_text(value)
    if not text.isdigit():
        return ""
    milliseconds = int(text)
    if milliseconds <= 0:
        return ""
    return str(milliseconds // 60000)


def extract_play_url(html_text: str) -> str:
    match = re.search(r"https://www\.disneyplus\.com/play/[0-9a-f\-]+", html_text, flags=re.IGNORECASE)
    return clean_text(match.group(0)) if match else ""


def category_text(value: Any) -> str:
    text = clean_text(value)
    if text.casefold().startswith("category:"):
        return clean_text(text.split(":", 1)[1])
    return text


def credits_from_details(credits: Any) -> tuple[list[str], list[str]]:
    directors: list[str] = []
    cast: list[str] = []
    if not isinstance(credits, list):
        return directors, cast
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        heading = clean_text(credit.get("heading")).casefold().rstrip(":")
        items = [
            clean_text(item.get("displayText"))
            for item in credit.get("items") or []
            if isinstance(item, dict) and clean_text(item.get("displayText"))
        ]
        if heading == "director":
            directors = dedupe_text(items)
        elif heading in {"cast", "starring"}:
            cast = dedupe_text(items)
    return directors, cast


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def split_values(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (list, tuple, set)):
        output: list[str] = []
        for value in values:
            output.extend(split_values(value))
        return output
    text = clean_text(values)
    return [text] if text else []


def clean_title(value: Any) -> str:
    text = clean_text(value)
    return re.sub(r"\s*\|\s*Watch on Disney\+\s*$", "", text, flags=re.IGNORECASE)


def dedupe_text(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        folded = text.casefold()
        if text and folded not in seen:
            output.append(text)
            seen.add(folded)
    return output


def nested_value(data: Any, path: tuple[Any, ...]) -> Any:
    current = data
    for step in path:
        if isinstance(step, int):
            if not isinstance(current, list) or step >= len(current):
                return None
            current = current[step]
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(step)
    return current


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text)
    return text.strip()
