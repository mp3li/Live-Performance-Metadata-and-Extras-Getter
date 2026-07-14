#!/usr/bin/env python3
"""
Netflix detail-page metadata helpers.

Netflix title pages expose a public HTML shell with JSON-LD and an embedded
GraphQL cache blob. This provider reads that structured page data instead of
guessing from rendered text.
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


NAME = "Netflix"
STUDIO_NAME = "Netflix"
PAGE_HOSTS = {"netflix.com", "www.netflix.com"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


@dataclass
class NetflixMetadata:
    source_url: str = ""
    detail_link: str = ""
    item_id: str = ""
    title: str = ""
    plot: str = ""
    year: str = ""
    content_rating: str = ""
    poster_url: str = ""
    wide_url: str = ""
    logo_url: str = ""
    trailer_url: str = ""
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    starring: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)


def is_netflix_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    host = parsed.netloc.casefold()
    return host in PAGE_HOSTS


def is_supported_url(url: str) -> bool:
    return bool(is_netflix_url(url) and title_id_from_url(url))


def title_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(clean_text(url))
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "title" and parts[1].isdigit():
        return parts[1]
    return ""


def extract_metadata(url: str, timeout: int = 25) -> NetflixMetadata:
    item_id = title_id_from_url(url)
    if not item_id:
        raise ValueError("Netflix links need a /title/ ID.")

    html_text = fetch_text(url, timeout=timeout)
    metadata = NetflixMetadata(
        source_url=canonical_url(html_text) or f"https://www.netflix.com/title/{item_id}",
        detail_link=url,
        item_id=item_id,
    )

    json_ld = extract_json_ld(html_text)
    graphql = extract_graphql_cache(html_text)

    apply_json_ld(metadata, json_ld)
    apply_graphql(metadata, graphql)
    apply_meta_fallbacks(metadata, html_text)

    if not metadata.title:
        raise ValueError("Netflix page did not expose a usable title.")
    if not metadata.starring and metadata.cast:
        metadata.starring = metadata.cast[:3]
    return metadata


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


def extract_json_ld(html_text: str) -> dict[str, Any]:
    match = re.search(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    try:
        data = json.loads(html.unescape(match.group(1).strip()))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def extract_graphql_cache(html_text: str) -> dict[str, Any]:
    match = re.search(
        r"reactContext\.models\.graphql\s*=\s*JSON\.parse\('(.*)'\);</script>",
        html_text,
        flags=re.DOTALL,
    )
    if not match:
        return {}
    raw = match.group(1)
    try:
        decoded = raw.encode("utf-8").decode("unicode_escape")
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    cache = data.get("data")
    return cache if isinstance(cache, dict) else {}


def apply_json_ld(metadata: NetflixMetadata, data: dict[str, Any]) -> None:
    metadata.title = clean_text(data.get("name")) or metadata.title
    metadata.plot = clean_text(data.get("description")) or metadata.plot
    metadata.content_rating = clean_text(data.get("contentRating")) or metadata.content_rating
    metadata.poster_url = clean_text(data.get("image")) or metadata.poster_url
    metadata.trailer_url = clean_text(nested_value(data, ("trailer", "contentUrl"))) or metadata.trailer_url

    date_created = clean_text(data.get("dateCreated"))
    if date_created:
        match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", date_created)
        if match:
            metadata.year = match.group(1)

    metadata.cast = [
        clean_text(actor.get("name"))
        for actor in data.get("actors") or []
        if isinstance(actor, dict) and clean_text(actor.get("name"))
    ] or metadata.cast
    metadata.directors = [
        clean_text(person.get("name"))
        for person in data.get("directors") or []
        if isinstance(person, dict) and clean_text(person.get("name"))
    ] or metadata.directors


def apply_graphql(metadata: NetflixMetadata, cache: dict[str, Any]) -> None:
    if not cache:
        return

    movie_key = f'Movie:{{"videoId":{metadata.item_id}}}'
    movie = cache.get(movie_key)
    if not isinstance(movie, dict):
        return

    metadata.title = clean_text(movie.get("title")) or metadata.title
    metadata.plot = clean_text(movie.get("shortSynopsis")) or metadata.plot
    metadata.year = clean_text(movie.get("latestYear")) or metadata.year
    metadata.content_rating = clean_text(
        nested_value(movie, ("contentAdvisory", "certificationValue"))
    ) or metadata.content_rating

    metadata.cast = resolve_people(cache, movie.get('persons:{"roles":"ACTOR"}')) or metadata.cast
    metadata.directors = resolve_people(cache, movie.get('persons:{"roles":"DIRECTOR"}')) or metadata.directors
    metadata.starring = metadata.cast[:3]
    metadata.genres = resolve_genres(cache, movie.get("genres")) or metadata.genres
    metadata.tags = resolve_tags(cache, movie.get("tags")) or metadata.tags

    metadata.logo_url = choose_artwork_url(movie, "LOGO_HORIZONTAL_CROPPED") or metadata.logo_url
    metadata.wide_url = (
        choose_artwork_url(movie, "ECLIPSE_BILLBOARD_REDUX")
        or choose_artwork_url(movie, "BILLBOARD")
        or metadata.wide_url
    )
    metadata.poster_url = choose_artwork_url(movie, "BOXSHOT") or metadata.poster_url

    trailer_url = resolve_supplemental_trailer(cache, movie)
    if trailer_url:
        metadata.trailer_url = trailer_url


def apply_meta_fallbacks(metadata: NetflixMetadata, html_text: str) -> None:
    metadata.poster_url = metadata.poster_url or meta_content(html_text, "og:image")
    metadata.wide_url = metadata.wide_url or meta_content(html_text, "og:image")
    metadata.trailer_url = metadata.trailer_url or meta_content(html_text, "og:video")


def canonical_url(html_text: str) -> str:
    match = re.search(
        r'<link\b[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']',
        html_text,
        flags=re.IGNORECASE,
    )
    return clean_text(html.unescape(match.group(1))) if match else ""


def meta_content(html_text: str, property_name: str) -> str:
    pattern = (
        r'<meta\b[^>]*(?:property|name)=["\']'
        + re.escape(property_name)
        + r'["\'][^>]*content=["\']([^"\']+)["\']'
    )
    match = re.search(pattern, html_text, flags=re.IGNORECASE)
    return clean_text(html.unescape(match.group(1))) if match else ""


def choose_artwork_url(movie: dict[str, Any], artwork_type: str) -> str:
    matches: list[tuple[int, str]] = []
    for key, value in movie.items():
        if artwork_type not in key or not isinstance(value, dict):
            continue
        url = clean_text(value.get("url"))
        if not url:
            continue
        width = int(value.get("width") or 0)
        matches.append((width, url))
    if not matches:
        return ""
    matches.sort(reverse=True)
    return matches[0][1]


def resolve_people(cache: dict[str, Any], connection: Any) -> list[str]:
    output: list[str] = []
    if not isinstance(connection, dict):
        return output
    for edge in connection.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node")
        if not isinstance(node, dict):
            continue
        ref = clean_text(node.get("__ref"))
        person = cache.get(ref)
        if not isinstance(person, dict):
            continue
        name = clean_text(person.get("name"))
        if name and name.casefold() not in {value.casefold() for value in output}:
            output.append(name)
    return output


def resolve_genres(cache: dict[str, Any], connection: Any) -> list[str]:
    output: list[str] = []
    if not isinstance(connection, dict):
        return output
    for edge in connection.get("edges") or []:
        ref = reference_from_edge(edge)
        genre = cache.get(ref)
        if not isinstance(genre, dict):
            continue
        name = clean_text(genre.get("title") or genre.get("name"))
        if name and name.casefold() not in {value.casefold() for value in output}:
            output.append(name)
    return output


def resolve_tags(cache: dict[str, Any], refs: Any) -> list[str]:
    output: list[str] = []
    if not isinstance(refs, list):
        return output
    for item in refs:
        if not isinstance(item, dict):
            continue
        ref = clean_text(item.get("__ref"))
        tag = cache.get(ref)
        if not isinstance(tag, dict):
            continue
        name = clean_text(tag.get("displayName"))
        if name and name.casefold() not in {value.casefold() for value in output}:
            output.append(name)
    return output


def resolve_supplemental_trailer(cache: dict[str, Any], movie: dict[str, Any]) -> str:
    connection = movie.get("supplementalVideosList")
    if isinstance(connection, dict):
        for edge in connection.get("edges") or []:
            ref = reference_from_edge(edge)
            video = cache.get(ref)
            url = playable_video_url(video)
            if url:
                return url

    promo_ref = clean_text(nested_value(movie, ('promoVideo({"context":{"uiContext":"BILLBOARD"}})', "__ref")))
    if promo_ref:
        url = playable_video_url(cache.get(promo_ref))
        if url:
            return url
    return ""


def playable_video_url(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    for key, value in node.items():
        if "playableVideo" not in key or not isinstance(value, dict):
            continue
        url = clean_text(value.get("url"))
        if url:
            return url
    return ""


def reference_from_edge(edge: Any) -> str:
    if not isinstance(edge, dict):
        return ""
    node = edge.get("node")
    if not isinstance(node, dict):
        return ""
    return clean_text(node.get("__ref"))


def nested_value(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current


def clean_text(value: Any) -> str:
    text = html.unescape("" if value is None else str(value))
    if any(marker in text for marker in ("Ã", "â", "ð")):
        try:
            text = text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            pass
    text = re.sub(r"\s+", " ", text)
    return text.strip()
