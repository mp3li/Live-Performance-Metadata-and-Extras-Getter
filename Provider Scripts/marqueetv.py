#!/usr/bin/env python3
"""
MarqueeTV detail-page metadata helpers.

MarqueeTV video pages expose a public VideoObject JSON-LD block and a public
JW Player trailer feed URL in the page HTML. This provider reads those
structured values instead of relying only on rendered text.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any


NAME = "MarqueeTV"
STUDIO_NAME = "MarqueeTV"
PAGE_HOSTS = {"marquee.tv", "www.marquee.tv"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
VISIBLE_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
VISIBLE_BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "br",
    "button",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "p",
    "section",
    "span",
    "ul",
}
KNOWN_CREW_ROLES = {
    "director": "director",
    "costume design": "costume_design",
    "composer": "composer",
}


@dataclass
class MarqueeTVActor:
    name: str = ""
    role: str = ""


@dataclass
class MarqueeTVMetadata:
    source_url: str = ""
    detail_link: str = ""
    slug: str = ""
    title: str = ""
    plot: str = ""
    outline: str = ""
    year: str = ""
    runtime_minutes: str = ""
    content_rating: str = ""
    language: str = ""
    poster_url: str = ""
    wide_url: str = ""
    trailer_url: str = ""
    upload_date: str = ""
    expires: str = ""
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cast: list[MarqueeTVActor] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    costume_designers: list[str] = field(default_factory=list)
    composers: list[str] = field(default_factory=list)
    gallery_urls: list[str] = field(default_factory=list)


def is_marqueetv_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    return parsed.netloc.casefold() in PAGE_HOSTS


def is_supported_url(url: str) -> bool:
    return bool(is_marqueetv_url(url) and slug_from_url(url))


def slug_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(clean_text(url))
    match = re.search(r"/videos/([^/?#]+)", parsed.path)
    return match.group(1) if match else ""


def extract_metadata(url: str, timeout: int = 25) -> MarqueeTVMetadata:
    slug = slug_from_url(url)
    if not slug:
        raise ValueError("MarqueeTV links need a /videos/ slug.")

    html_text = fetch_text(url, timeout=timeout)
    video_object = extract_video_object(html_text)
    visible_lines = extract_visible_lines(html_text)

    metadata = MarqueeTVMetadata(
        source_url=clean_text(video_object.get("embedUrl")) or f"https://marquee.tv/videos/{slug}",
        detail_link=url,
        slug=slug,
    )

    apply_video_object(metadata, video_object)
    apply_visible_text(metadata, visible_lines)
    apply_meta_fallbacks(metadata, html_text)
    apply_trailer_feed(metadata, html_text, timeout=timeout)

    if not metadata.title:
        raise ValueError("MarqueeTV page did not expose a usable title.")
    if not metadata.plot and metadata.outline:
        metadata.plot = metadata.outline
    if not metadata.outline and metadata.plot:
        metadata.outline = metadata.plot
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


def fetch_json(url: str, timeout: int = 25) -> dict[str, Any]:
    text = fetch_text(url, timeout=timeout)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("MarqueeTV trailer feed returned an unexpected response.")
    return data


def extract_video_object(html_text: str) -> dict[str, Any]:
    for match in re.finditer(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = html.unescape(match.group(1).strip())
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in iter_json_ld_objects(data):
            if clean_text(item.get("@type")).casefold() == "videoobject":
                return item
    return {}


def iter_json_ld_objects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        output = [value]
        graph = value.get("@graph")
        if isinstance(graph, list):
            output.extend(item for item in graph if isinstance(item, dict))
        return output
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def apply_video_object(metadata: MarqueeTVMetadata, data: dict[str, Any]) -> None:
    metadata.title = clean_text(data.get("name")) or metadata.title
    metadata.plot = clean_text(data.get("description")) or metadata.plot
    metadata.outline = metadata.plot or metadata.outline
    metadata.poster_url, metadata.wide_url, metadata.gallery_urls = classify_image_urls(
        data.get("thumbnailUrl")
    )
    metadata.upload_date = clean_text(data.get("uploadDate"))
    metadata.expires = clean_text(data.get("expires"))
    metadata.language = language_name(data.get("inLanguage"))
    metadata.runtime_minutes = iso_duration_to_minutes(data.get("duration"))
    metadata.genres = [normalize_genre_text(value) for value in dedupe_text(split_values(data.get("genre")))]

    copyright_year = clean_text(data.get("copyrightYear"))
    if re.fullmatch(r"(18\d{2}|19\d{2}|20\d{2}|21\d{2})", copyright_year):
        metadata.year = copyright_year

    for token in split_keyword_tokens(data.get("keywords")):
        role_match = re.fullmatch(r"(.+?)\s+\((.+)\)", token)
        if role_match:
            name = clean_text(role_match.group(1))
            role = clean_text(role_match.group(2))
            role_key = role.casefold()
            bucket = KNOWN_CREW_ROLES.get(role_key)
            if bucket == "director":
                add_unique(metadata.directors, name)
            elif bucket == "costume_design":
                add_unique(metadata.costume_designers, name)
            elif bucket == "composer":
                add_unique(metadata.composers, name)
            elif name and role:
                add_actor(metadata.cast, name, role)
            continue

        if re.fullmatch(r"(18\d{2}|19\d{2}|20\d{2}|21\d{2})", token):
            metadata.year = token
            continue
        lowered = token.casefold()
        if lowered in {"recently added"}:
            add_unique(metadata.tags, token)
            continue
        if lowered not in {value.casefold() for value in metadata.genres}:
            add_unique(metadata.tags, token)


def apply_visible_text(metadata: MarqueeTVMetadata, lines: list[str]) -> None:
    summary_pattern = re.compile(
        r"^(?P<genre>[A-Za-z][A-Za-z &/\-]+)\s+(?P<minutes>\d+)\s+min\s+"
        r"(?P<year>18\d{2}|19\d{2}|20\d{2}|21\d{2})(?:\s+(?P<rating>[A-Za-z0-9+\-]+))?$"
    )
    runtime_line = re.compile(r"^(?P<minutes>\d+)\s+min$")
    year_line = re.compile(r"^(18\d{2}|19\d{2}|20\d{2}|21\d{2})$")
    for line in lines:
        match = summary_pattern.match(line)
        if not match:
            continue
        add_unique(metadata.genres, normalize_genre_text(match.group("genre")))
        metadata.runtime_minutes = clean_text(match.group("minutes")) or metadata.runtime_minutes
        metadata.year = clean_text(match.group("year")) or metadata.year
        metadata.content_rating = clean_text(match.group("rating")) or metadata.content_rating
        break
    else:
        for index in range(len(lines) - 2):
            genre = clean_text(lines[index])
            runtime_match = runtime_line.match(lines[index + 1])
            year_match = year_line.match(lines[index + 2])
            if not genre or not runtime_match or not year_match:
                continue
            if genre.casefold() in {"play", "trailer", "cast", "director", "original language"}:
                continue
            add_unique(metadata.genres, normalize_genre_text(genre))
            metadata.runtime_minutes = runtime_match.group("minutes")
            metadata.year = year_match.group(1)
            if index + 3 < len(lines):
                rating = clean_text(lines[index + 3])
                if rating and rating.casefold() not in {"play", "trailer"}:
                    metadata.content_rating = rating
            break

    visible_text = "\n".join(lines)
    if not metadata.language:
        for index, line in enumerate(lines):
            if line.casefold() != "original language":
                continue
            if index + 1 < len(lines):
                metadata.language = clean_text(lines[index + 1])
                break
        if not metadata.language:
            match = re.search(r"\bOriginal Language\s+([A-Za-z][A-Za-z .\-]+)", visible_text)
            if match:
                metadata.language = clean_text(match.group(1))

    if not metadata.directors:
        for index, line in enumerate(lines):
            if line.casefold() != "director":
                continue
            if index + 1 < len(lines):
                add_unique(metadata.directors, lines[index + 1])
                break
        if not metadata.directors:
            match = re.search(r"\bDirector\s+([A-Za-z][A-Za-z .'\-]+)", visible_text)
            if match:
                add_unique(metadata.directors, match.group(1))

    if not metadata.cast:
        match = re.search(
            r"\bCast\s+(.+?)(?:\bDirector\b|\bOriginal Language\b|\bYou may also like\b)",
            visible_text,
            flags=re.DOTALL,
        )
        if match:
            for token in split_keyword_tokens(match.group(1).replace("Read More", "")):
                role_match = re.fullmatch(r"(.+?)\s+\((.+)\)", token)
                if role_match:
                    add_actor(metadata.cast, role_match.group(1), role_match.group(2))


def apply_meta_fallbacks(metadata: MarqueeTVMetadata, html_text: str) -> None:
    og_image = meta_content(html_text, "og:image")
    twitter_image = meta_content(html_text, "twitter:image")
    if not metadata.wide_url:
        metadata.wide_url = og_image or twitter_image
    if not metadata.poster_url:
        metadata.poster_url = twitter_image or og_image


def apply_trailer_feed(metadata: MarqueeTVMetadata, html_text: str, timeout: int) -> None:
    feed_url = extract_trailer_feed_url(html_text)
    if not feed_url:
        return
    try:
        data = fetch_json(feed_url, timeout=timeout)
    except Exception:
        return

    metadata.trailer_url = choose_best_trailer_mp4(data) or metadata.trailer_url
    if not metadata.poster_url:
        metadata.poster_url = clean_text(nested_value(data, ("playlist", 0, "image")))


def extract_trailer_feed_url(html_text: str) -> str:
    match = re.search(
        r"https://cdn\.jwplayer\.com/v2/media/[A-Za-z0-9]+(?:\?token=[^\"'<>\\ ]+)?",
        html_text,
        flags=re.IGNORECASE,
    )
    return clean_text(html.unescape(match.group(0))) if match else ""


def choose_best_trailer_mp4(data: dict[str, Any]) -> str:
    best_url = ""
    best_score = -1
    playlist = data.get("playlist")
    if not isinstance(playlist, list):
        return ""
    for item in playlist:
        if not isinstance(item, dict):
            continue
        for source in item.get("sources") or []:
            if not isinstance(source, dict):
                continue
            if clean_text(source.get("type")).casefold() != "video/mp4":
                continue
            url = clean_text(source.get("file"))
            if not url:
                continue
            height = int(clean_text(source.get("height")) or "0")
            bitrate = int(clean_text(source.get("bitrate")) or "0")
            score = height * 100000 + bitrate
            if score > best_score:
                best_score = score
                best_url = url
    return best_url


def classify_image_urls(value: Any) -> tuple[str, str, list[str]]:
    urls = [clean_text(url) for url in split_values(value) if clean_text(url)]
    poster = ""
    wide = ""
    gallery: list[str] = []

    for url in urls:
        lowered = url.casefold()
        if not poster and ("1536x2304" in lowered or "poster" in lowered):
            poster = strip_query(url)
            continue
        if not wide and ("1920x1080" in lowered or "1280x720" in lowered):
            wide = strip_query(url)
            continue

    for url in urls:
        cleaned = strip_query(url)
        if cleaned and cleaned not in {poster, wide}:
            gallery.append(cleaned)

    if not wide and urls:
        wide = strip_query(urls[0])
    if not poster:
        for url in urls:
            cleaned = strip_query(url)
            if cleaned != wide:
                poster = cleaned
                break
    return poster, wide, dedupe_text(gallery)


def strip_query(url: str) -> str:
    text = clean_text(url)
    if not text:
        return ""
    parsed = urllib.parse.urlsplit(text)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def meta_content(html_text: str, property_name: str) -> str:
    match = re.search(
        rf'<meta\b[^>]*(?:property|name)=["\']{re.escape(property_name)}["\'][^>]*content=["\']([^"\']+)["\']',
        html_text,
        flags=re.IGNORECASE,
    )
    return clean_text(html.unescape(match.group(1))) if match else ""


class VisibleTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in VISIBLE_SKIP_TAGS:
            self.skip_depth += 1
            return
        if not self.skip_depth and lowered in VISIBLE_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in VISIBLE_SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if not self.skip_depth and lowered in VISIBLE_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and data:
            self.parts.append(data)


def extract_visible_lines(html_text: str) -> list[str]:
    parser = VisibleTextExtractor()
    parser.feed(html_text)
    text = html.unescape("".join(parser.parts))
    lines = [clean_text(line) for line in text.splitlines()]
    return [line for line in lines if line]


def iso_duration_to_minutes(value: Any) -> str:
    text = clean_text(value).upper()
    if not text:
        return ""
    match = re.fullmatch(
        r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        text,
    )
    if not match:
        return ""
    hours = int(match.group("hours") or "0")
    minutes = int(match.group("minutes") or "0")
    seconds = int(match.group("seconds") or "0")
    total_seconds = hours * 3600 + minutes * 60 + seconds
    rounded_minutes = (total_seconds + 30) // 60
    return str(rounded_minutes) if rounded_minutes else ""


def split_keyword_tokens(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    return dedupe_text([part for part in re.split(r"\s*,\s*", text) if clean_text(part)])


def language_name(value: Any) -> str:
    text = clean_text(value)
    lowered = text.casefold()
    mapping = {
        "en": "English",
        "en-us": "English",
        "en-gb": "English",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
        "it": "Italian",
        "ja": "Japanese",
    }
    return mapping.get(lowered, text)


def nested_value(value: Any, path: tuple[Any, ...]) -> Any:
    current = value
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


def split_values(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (list, tuple, set)):
        output: list[str] = []
        for value in values:
            output.extend(split_values(value))
        return output
    return [clean_text(values)] if clean_text(values) else []


def add_unique(values: list[str], value: Any) -> None:
    text = clean_text(value)
    if text and text.casefold() not in {item.casefold() for item in values}:
        values.append(text)


def normalize_genre_text(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    return text.title() if text.islower() else text


def add_actor(actors: list[MarqueeTVActor], name: Any, role: Any) -> None:
    actor_name = clean_text(name)
    actor_role = clean_text(role)
    if not actor_name:
        return
    key = (actor_name.casefold(), actor_role.casefold())
    seen = {(item.name.casefold(), item.role.casefold()) for item in actors}
    if key not in seen:
        actors.append(MarqueeTVActor(name=actor_name, role=actor_role))


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


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text)
    return text.strip()
