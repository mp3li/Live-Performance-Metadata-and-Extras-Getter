#!/usr/bin/env python3
"""
Amazon Prime Video detail-page extraction helpers.

This module intentionally keeps Amazon-specific page knowledge out of the
generic NFO writer. It reads the HTML/text returned by an Amazon detail page and
returns cleaned metadata fields that match the visible detail page.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field


NAME = "Amazon Prime Video"
GENRE_SEPARATOR = "\u2022"

CONTENT_RATINGS = {
    "G",
    "PG",
    "PG-13",
    "R",
    "NC-17",
    "TV-Y",
    "TV-Y7",
    "TV-G",
    "TV-PG",
    "TV-14",
    "TV-MA",
}

NON_DETAIL_LINES = {
    "add another link",
    "clear",
    "creators and cast",
    "customers also watched",
    "explore",
    "free to me",
    "join prime",
    "like",
    "loading",
    "menu",
    "more ways to watch",
    "not for me",
    "redeem a gift card or promotion code",
    "relateddetailsexplore",
    "rent hd",
    "share",
    "30-day free trial",
    "subscriptions",
    "terms apply",
    "watch trailer",
    "watchlist",
}

SECTION_LABELS = {
    "cast",
    "directors",
    "producers",
    "studio",
}

@dataclass
class AmazonMetadata:
    title: str = ""
    plot: str = ""
    tagline: str = ""
    year: str = ""
    runtime_minutes: str = ""
    imdb_rating: str = ""
    customer_rating: str = ""
    content_rating: str = ""
    poster_url: str = ""
    banner_url: str = ""
    trailer_url: str = ""
    trailer_asset_id: str = ""
    trailer_playback_id: str = ""
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    producers: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)


def is_amazon_url(url: str) -> bool:
    host = urllib.parse.urlparse(clean_text(url)).netloc.casefold()
    return host == "amazon.com" or host.endswith(".amazon.com")


def extract_metadata(
    html_text: str, visible_text: str, source_url: str = "", detail_link: str = ""
) -> AmazonMetadata:
    if not (is_amazon_url(source_url) or is_amazon_url(detail_link)):
        return AmazonMetadata()

    lines = parse_lines(visible_text)
    metadata = AmazonMetadata()
    metadata.title = find_title(lines) or find_html_title(html_text)
    metadata.plot = find_plot(lines)
    metadata.tagline = find_tagline(lines)
    metadata.genres = find_genres(lines)
    metadata.customer_rating = find_customer_rating(lines)
    metadata.content_rating = find_content_rating(lines)
    images = find_image_urls(html_text)
    metadata.poster_url = images.get("packshot") or images.get("covershot") or images.get("titleshot")
    metadata.banner_url = images.get("heroshot") or images.get("covershot")

    trailer = find_trailer_metadata(html_text, source_url or detail_link)
    metadata.trailer_url = trailer.get("url", "")
    metadata.trailer_asset_id = trailer.get("asset_id", "")
    metadata.trailer_playback_id = trailer.get("playback_id", "")

    imdb_rating, year, runtime = find_imdb_year_runtime(lines)
    metadata.imdb_rating = imdb_rating
    metadata.year = year
    metadata.runtime_minutes = runtime

    metadata.directors = find_label_values(lines, "Directors")
    metadata.producers = find_label_values(lines, "Producers")
    metadata.cast = find_label_values(lines, "Cast")
    metadata.studios = find_label_values(lines, "Studio")
    return metadata


def parse_lines(visible_text: str) -> list[str]:
    lines = []
    for line in visible_text.splitlines():
        cleaned = clean_text(line)
        if cleaned:
            lines.append(cleaned)
    return lines


def clean_text(value: object) -> str:
    text = html.unescape("" if value is None else str(value))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_title(value: str) -> str:
    title = clean_text(value)
    title = re.sub(r"^Watch\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\|\s*(?:Prime Video|Amazon(?:\.com)?)\s*$", "", title, flags=re.IGNORECASE)
    return title


def find_html_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = clean_title(re.sub(r"<[^>]+>", " ", match.group(1)))
    return title if is_title_candidate(title) else ""


def find_title(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if is_genre_line(line) and index > 0:
            candidate = find_previous_title_candidate(lines, index)
            if candidate:
                return candidate

    for index, line in enumerate(lines):
        if line.casefold() == "watch trailer" and index > 0:
            candidate = find_previous_title_candidate(lines, index)
            if candidate:
                return candidate

    return ""


def find_previous_title_candidate(lines: list[str], before_index: int) -> str:
    for candidate in reversed(lines[max(0, before_index - 6) : before_index]):
        title = clean_title(candidate)
        if is_title_candidate(title):
            return title
    return ""


def is_title_candidate(value: str) -> bool:
    text = clean_text(value)
    if not text or is_non_detail_line(text):
        return False
    if is_genre_line(text) or is_rating_or_runtime_line(text) or is_year_runtime_line(text):
        return False
    if text.casefold() in SECTION_LABELS:
        return False
    if re.fullmatch(r"\d{4}", text):
        return False
    if len(text) > 90 and re.search(r"[.!?](?:\s|$)", text):
        return False
    return 2 <= len(text) <= 160


def find_plot(lines: list[str]) -> str:
    for line in lines:
        if len(line) < 70:
            continue
        if is_non_detail_line(line):
            continue
        if GENRE_SEPARATOR in line:
            continue
        if re.search(r"\b(Amazon|IMDbPro|Kindle|Goodreads)\b", line):
            continue
        return line
    return ""


def find_tagline(lines: list[str]) -> str:
    for index, line in enumerate(lines[:-1]):
        next_line = lines[index + 1]
        if (
            15 <= len(line) <= 90
            and len(next_line) >= 70
            and not is_non_detail_line(line)
            and not is_rating_or_runtime_line(line)
            and not is_genre_line(line)
        ):
            return line
    return ""


def find_genres(lines: list[str]) -> list[str]:
    for line in lines:
        if not is_genre_line(line):
            continue
        return dedupe([part.strip() for part in line.split(GENRE_SEPARATOR) if part.strip()])
    return []


def is_genre_line(line: str) -> bool:
    if GENRE_SEPARATOR not in line:
        return False
    if is_non_detail_line(line):
        return False
    parts = [part.strip() for part in line.split(GENRE_SEPARATOR) if part.strip()]
    return len(parts) >= 2 and all(1 < len(part) <= 80 for part in parts)


def find_customer_rating(lines: list[str]) -> str:
    for line in lines:
        match = re.fullmatch(r"(\d+(?:\.\d+)?/5)", line)
        if match:
            return match.group(1)
    return ""


def is_rating_or_runtime_line(line: str) -> bool:
    text = clean_text(line)
    return bool(
        re.fullmatch(r"\d+(?:\.\d+)?/5", text)
        or re.search(r"\bIMDb\s+\d+(?:\.\d+)?/10", text, flags=re.IGNORECASE)
        or re.search(r"\b\d+\s*h(?:ours?)?\s*\d*\s*m?", text, flags=re.IGNORECASE)
    )


def is_year_runtime_line(line: str) -> bool:
    return bool(
        re.fullmatch(
            r"(18\d{2}|19\d{2}|20\d{2}|21\d{2})\s*(?:\d+\s*h(?:ours?)?)?\s*(?:\d+\s*m(?:in(?:ute)?s?)?)?",
            clean_text(line),
            flags=re.IGNORECASE,
        )
    )


def find_imdb_year_runtime(lines: list[str]) -> tuple[str, str, str]:
    for line in lines:
        match = re.search(
            r"IMDb\s+(\d+(?:\.\d+)?)/10\s*(18\d{2}|19\d{2}|20\d{2}|21\d{2})\s*(.+)",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        runtime = parse_runtime_minutes(match.group(3))
        return match.group(1), match.group(2), runtime

    for line in lines:
        match = re.search(
            r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\s*((?:\d+\s*h(?:ours?)?)?\s*(?:\d+\s*m(?:in(?:ute)?s?)?)?)",
            clean_text(line),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        runtime = parse_runtime_minutes(match.group(2))
        if runtime:
            return "", match.group(1), runtime
    return "", "", ""


def parse_runtime_minutes(text: str) -> str:
    match = re.search(
        r"(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?",
        clean_text(text),
        flags=re.IGNORECASE,
    )
    if not match or not (match.group(1) or match.group(2)):
        return ""
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total = hours * 60 + minutes
    return str(total) if total else ""


def find_content_rating(lines: list[str]) -> str:
    for line in lines:
        text = clean_text(line).upper()
        if text in CONTENT_RATINGS:
            return text
    return ""


def find_label_values(lines: list[str], label: str) -> list[str]:
    label_folded = label.casefold()
    for index, line in enumerate(lines[:-1]):
        if line.casefold() != label_folded:
            continue
        if label_folded == "studio":
            return find_single_line_label_values(lines, index)
        values: list[str] = []
        for value in lines[index + 1 :]:
            folded = value.casefold()
            if folded in SECTION_LABELS or is_non_detail_line(value):
                break
            values.extend(split_names(value))
        return values
    return []


def find_single_line_label_values(lines: list[str], label_index: int) -> list[str]:
    for value in lines[label_index + 1 :]:
        folded = value.casefold()
        if folded in SECTION_LABELS:
            return []
        if is_non_detail_line(value):
            continue
        return split_names(value)
    return []


def split_names(value: str) -> list[str]:
    return dedupe([part.strip() for part in clean_text(value).split(",") if part.strip()])


def find_image_urls(html_text: str) -> dict[str, str]:
    images: dict[str, str] = {}
    for key in ("packshot", "covershot", "heroshot", "titleshot"):
        match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', html_text)
        if match:
            url = decode_json_string(match.group(1))
            if is_image_url(url):
                images[key] = url

    fallback = find_poster_url(html_text)
    if fallback and "packshot" not in images:
        images["packshot"] = fallback
    return images


def find_poster_url(html_text: str) -> str:
    for tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE):
        attrs = {
            key.casefold(): html.unescape(value)
            for key, value in re.findall(r'([\w:-]+)=["\']([^"\']*)["\']', tag)
        }
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or ""
        if key.casefold() not in {"og:image", "twitter:image", "image", "thumbnailurl"}:
            continue
        content = attrs.get("content") or attrs.get("value") or ""
        if is_image_url(content):
            return content

    for match in re.finditer(
        r"https://m\.media-amazon\.com/images/I/[^\"'<>\\\s]+",
        html_text,
        flags=re.IGNORECASE,
    ):
        candidate = html.unescape(match.group(0))
        if is_image_url(candidate):
            return candidate
    return ""


def find_trailer_metadata(html_text: str, base_url: str) -> dict[str, str]:
    trailer: dict[str, str] = {}

    direct_url = find_direct_trailer_media_url(html_text)
    if direct_url:
        trailer["url"] = direct_url

    asset_match = re.search(
        r'"autoplayTrailerHero"\s*:\s*\{.*?"assetId"\s*:\s*"([^"]+)"',
        html_text,
        flags=re.DOTALL,
    )
    if asset_match:
        trailer["asset_id"] = decode_json_string(asset_match.group(1))

    for match in re.finditer(r'"isTrailer"\s*:\s*true', html_text):
        window = html_text[match.start() : match.start() + 5000]
        playback_id = re.search(r'"playbackID"\s*:\s*"([^"]+)"', window)
        playback_url = re.search(r'"playbackURL"\s*:\s*"([^"]+)"', window)
        if playback_id:
            trailer["playback_id"] = decode_json_string(playback_id.group(1))
        if playback_url:
            url = decode_json_string(playback_url.group(1))
            trailer.setdefault("url", urllib.parse.urljoin(base_url, url))
        if trailer.get("url") or trailer.get("playback_id"):
            break

    return trailer


def find_direct_trailer_media_url(html_text: str) -> str:
    candidates: list[str] = []
    for match in re.finditer(r'https?://[^"\'<>\\\s]+', html_text):
        candidate = decode_json_string(html.unescape(match.group(0)))
        if is_direct_trailer_media_url(candidate):
            candidates.append(candidate)
    for candidate in candidates:
        if urllib.parse.urlparse(candidate).path.casefold().endswith(".mp4"):
            return candidate
    return candidates[0] if candidates else ""


def is_direct_trailer_media_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    if parsed.scheme not in {"http", "https"}:
        return False
    path = parsed.path.casefold()
    if not path.endswith((".mp4", ".m3u8", ".mpd")):
        return False
    text = (parsed.path + "?" + parsed.query).casefold()
    return "trailer" in text or "video_" in text


def decode_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return html.unescape(value).replace("\\u0026", "&").replace("\\/", "/")


def is_image_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    path = parsed.path.casefold()
    if any(path.endswith(ext) for ext in (".woff", ".woff2", ".css", ".js")):
        return False
    return bool(
        re.search(r"\.(?:jpg|jpeg|png|webp)(?:$|[._-])", path)
        or "_fmjpg_" in path
        or "_fmpng_" in path
    )


def is_non_detail_line(line: str) -> bool:
    text = clean_text(line).casefold()
    if text in NON_DETAIL_LINES:
        return True
    if (
        text.startswith("explore the ")
        or text.startswith("get info ")
        or text.startswith("subscribe to ")
    ):
        return True
    return False


def dedupe(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        cleaned = clean_text(value)
        folded = cleaned.casefold()
        if cleaned and folded not in seen:
            output.append(cleaned)
            seen.add(folded)
    return output
