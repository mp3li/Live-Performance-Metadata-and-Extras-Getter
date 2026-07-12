#!/usr/bin/env python3
"""
Live Performance Metadata and Extras Getter by mp3li.

Scrapes publicly available detail-page HTML and writes Jellyfin-readable .nfo
metadata files. The tool intentionally uses only the Python standard library so
it can run without installing packages. Embedded video extras can also be
downloaded as MP4 files when yt-dlp is installed.
"""

from __future__ import annotations

import html
import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_SCRIPTS_DIR = PROJECT_ROOT / "Provider Scripts"
UNSUPPORTED_PROVIDER_MESSAGE = (
    "Unfortunately this tool does not cover that provider at this time. "
    "Please make an Issue on Github for a Feature Request."
)


def load_provider_script(module_name: str) -> Any:
    path = PROVIDER_SCRIPTS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"provider_scripts.{module_name}", path)
    if not spec or not spec.loader:
        raise ImportError(f"Could not load provider script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


amazon = load_provider_script("amazon")
operavision = load_provider_script("operavision")
metopera = load_provider_script("metopera")
broadwayhd = load_provider_script("broadwayhd")

PROVIDER_HANDLERS = (
    ("amazon", amazon.NAME, amazon.is_amazon_url),
    ("operavision", operavision.NAME, operavision.is_operavision_url),
    ("metopera", metopera.NAME, metopera.is_supported_url),
    ("broadwayhd", broadwayhd.NAME, broadwayhd.is_supported_url),
)


WELCOME_MESSAGE = """
Welcome to Live Performance Metadata and Extras Getter by mp3li

This tool scrapes publicly available detail pages from supported providers and turns them into Jellyfin-style .nfo metadata. It also downloads available trailers and images, names them with Jellyfin-friendly artwork filenames, and saves everything in the Output folder.
"""

HTTP_TIMEOUT_SECONDS = 25
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
CHROME_APP_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
TRAILER_CAPTURE_TIMEOUT_SECONDS = 30
EXTERNAL_VIDEO_DOWNLOAD_TIMEOUT_SECONDS = 900
MY_LINKS_DIR_NAME = "My Links Txt"
MY_LINKS_FILE_NAME = "mylinks.txt"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36 "
    "mp3li-live-performance-metadata-and-extras-getter/1.0"
)
ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
WIDE_ART_SUFFIXES = ("fanart", "banner", "landscape")
SUPPORTED_PROVIDER_NAMES = tuple(name for _key, name, _matcher in PROVIDER_HANDLERS)
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "caption",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}

SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg"}

TECH_META_KEYS = {
    "anti-csrftoken-a2z",
    "bidi-endpoint",
    "charset",
    "encrypted-slate-token",
    "flow-closure-id",
    "format-detection",
    "favicon-generator",
    "generator",
    "handheldfriendly",
    "bingbot",
    "googlebot",
    "mobileoptimized",
    "msapplication-tilecolor",
    "referrer",
    "robots",
    "theme-color",
    "viewport",
    "x-dns-prefetch-control",
}

TECH_META_PREFIXES = (
    "anti-csrf",
    "csrf",
    "encrypted-",
    "flow-",
    "msapplication-",
)

MARKETING_VALUES = {
    "7-day free trial",
    "clear",
    "free to me",
    "join prime",
    "prime",
    "rent hd",
    "subscriptions",
    "terms apply",
    "watch trailer",
}

LABEL_MAP = {
    "air date": "date",
    "aired": "date",
    "artist": "cast",
    "artists": "cast",
    "cast": "cast",
    "categories": "genre",
    "category": "genre",
    "company": "studio",
    "content rating": "content_rating",
    "country": "country",
    "credits": "credits",
    "date": "date",
    "directed by": "director",
    "director": "director",
    "directors": "director",
    "duration": "runtime",
    "event date": "date",
    "executive producer": "credits",
    "executive producers": "credits",
    "filmed": "date",
    "filmed date": "date",
    "genre": "genre",
    "genres": "genre",
    "host": "cast",
    "hosts": "cast",
    "language": "language",
    "length": "runtime",
    "location": "location",
    "mpaa": "content_rating",
    "name": "title",
    "overview": "plot",
    "performer": "cast",
    "performers": "cast",
    "plot": "plot",
    "premiere": "date",
    "premiered": "date",
    "production": "studio",
    "production company": "studio",
    "production date": "date",
    "producer": "credits",
    "producers": "credits",
    "rating": "rating",
    "recorded": "date",
    "recorded date": "date",
    "release date": "date",
    "released": "date",
    "runtime": "runtime",
    "site": "studio",
    "studio": "studio",
    "studios": "studio",
    "starring": "cast",
    "summary": "plot",
    "synopsis": "plot",
    "tagline": "tagline",
    "tags": "tag",
    "title": "title",
    "venue": "location",
    "writer": "writer",
    "writers": "writer",
    "written by": "writer",
}

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass
class Actor:
    name: str
    role: str = ""


@dataclass
class ExtraMedia:
    title: str
    kind: str = ""
    description: str = ""
    url: str = ""
    page_url: str = ""
    external_url: str = ""


@dataclass
class Metadata:
    source_url: str
    detail_link: str = ""
    source_site: str = ""
    title: str = ""
    original_title: str = ""
    sort_title: str = ""
    plot: str = ""
    outline: str = ""
    tagline: str = ""
    year: str = ""
    date: str = ""
    runtime_minutes: str = ""
    content_rating: str = ""
    numeric_rating: str = ""
    amazon_rating: str = ""
    imdb_rating: str = ""
    language: str = ""
    poster_url: str = ""
    fanart_url: str = ""
    logo_url: str = ""
    trailer_url: str = ""
    trailer_asset_id: str = ""
    trailer_playback_id: str = ""
    local_poster_path: str = ""
    local_fanart_path: str = ""
    local_logo_path: str = ""
    local_trailer_path: str = ""
    production_label: str = "Production/Studio"
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    writers: list[str] = field(default_factory=list)
    credits: list[str] = field(default_factory=list)
    actors: list[Actor] = field(default_factory=list)
    unique_ids: dict[str, str] = field(default_factory=dict)
    extra_fields: dict[str, list[str]] = field(default_factory=dict)
    gallery_urls: list[str] = field(default_factory=list)
    extra_videos: list[ExtraMedia] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def set_once(self, field_name: str, value: Any) -> None:
        text = clean_text(value)
        if text and not getattr(self, field_name):
            setattr(self, field_name, text)

    def add_values(self, field_name: str, values: Any) -> None:
        current = getattr(self, field_name)
        seen = {item.casefold() for item in current}
        for value in split_values(values):
            if field_name in {"genres", "tags"} and is_ignored_metadata_value(value):
                continue
            folded = value.casefold()
            if folded and folded not in seen:
                current.append(value)
                seen.add(folded)

    def add_actors(self, values: Any) -> None:
        seen = {(actor.name.casefold(), actor.role.casefold()) for actor in self.actors}
        for actor in parse_actors(values):
            key = (actor.name.casefold(), actor.role.casefold())
            if actor.name and key not in seen:
                self.actors.append(actor)
                seen.add(key)

    def add_extra(self, label: str, value: Any) -> None:
        label_text = clean_text(label)
        value_text = clean_text(value)
        if not label_text or not value_text:
            return
        bucket = self.extra_fields.setdefault(label_text, [])
        if value_text.casefold() not in {item.casefold() for item in bucket}:
            bucket.append(value_text)

    def add_unique_id(self, provider: str, value: str) -> None:
        provider = clean_text(provider).casefold()
        value = clean_text(value)
        if provider and value and provider not in self.unique_ids:
            self.unique_ids[provider] = value


@dataclass
class SaveResult:
    folder: Path
    items: list[Path]


@dataclass
class LinkEntry:
    title: str
    url: str


class UnsupportedProviderError(ValueError):
    pass


class AnimatedStatus:
    def __init__(self, message: str) -> None:
        self.message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = sys.stdout.isatty()

    def __enter__(self) -> "AnimatedStatus":
        if not self._enabled:
            print(self.message + "...")
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        if self._enabled:
            sys.stdout.write("\r" + " " * (len(self.message) + 8) + "\r")
            sys.stdout.flush()

    def _run(self) -> None:
        frames = ("   ", ".  ", ".. ", "...")
        index = 0
        while not self._stop_event.is_set():
            sys.stdout.write("\r" + self.message + frames[index % len(frames)])
            sys.stdout.flush()
            index += 1
            self._stop_event.wait(0.35)


class DetailPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta_tags: list[dict[str, str]] = []
        self.link_tags: list[dict[str, str]] = []
        self.json_ld_scripts: list[str] = []
        self.headings: list[str] = []
        self._text_parts: list[str] = []
        self._script_parts: list[str] = []
        self._heading_parts: list[str] = []
        self._capture_title = False
        self._capture_json_ld = False
        self._capture_heading = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {name.lower(): value or "" for name, value in attrs}

        if tag == "meta":
            self.meta_tags.append(attr_map)
        elif tag == "link":
            self.link_tags.append(attr_map)

        if tag == "title":
            self._capture_title = True
        elif tag == "script" and "ld+json" in attr_map.get("type", "").lower():
            self._capture_json_ld = True
            self._script_parts = []
        elif tag in SKIP_TEXT_TAGS:
            self._skip_depth += 1
        elif tag in {"h1", "h2", "h3"}:
            self._capture_heading = True
            self._heading_parts = []

        if tag in BLOCK_TAGS and not self._skip_depth:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag == "title":
            self._capture_title = False
        elif tag == "script" and self._capture_json_ld:
            script = clean_text(" ".join(self._script_parts))
            if script:
                self.json_ld_scripts.append(script)
            self._capture_json_ld = False
            self._script_parts = []
        elif tag in SKIP_TEXT_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in {"h1", "h2", "h3"} and self._capture_heading:
            heading = clean_text(" ".join(self._heading_parts))
            if heading:
                self.headings.append(heading)
            self._capture_heading = False
            self._heading_parts = []

        if tag in BLOCK_TAGS and not self._skip_depth:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self.title_parts.append(data)
        elif self._capture_json_ld:
            self._script_parts.append(data)
        elif not self._skip_depth:
            self._text_parts.append(data)
            if self._capture_heading:
                self._heading_parts.append(data)

    @property
    def title(self) -> str:
        return clean_text(" ".join(self.title_parts))

    @property
    def visible_text(self) -> str:
        return clean_text_preserving_lines("".join(self._text_parts))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(clean_text(item) for item in value)
    elif isinstance(value, dict):
        value = value.get("name") or value.get("@id") or json.dumps(value, ensure_ascii=False)
    text = html.unescape(str(value))
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_text_preserving_lines(value: str) -> str:
    text = html.unescape(value).replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_ignored_metadata_value(value: Any) -> bool:
    text = clean_text(value).casefold()
    return not text or text in MARKETING_VALUES


def is_technical_meta_key(key: str) -> bool:
    normalized = clean_text(key).casefold()
    return normalized in TECH_META_KEYS or any(
        normalized.startswith(prefix) for prefix in TECH_META_PREFIXES
    )


def should_keep_unmapped_visible_field(meta: Metadata, label: str, value: str) -> bool:
    if amazon.is_amazon_url(meta.source_url) or amazon.is_amazon_url(
        meta.detail_link
    ):
        return False
    if operavision.is_operavision_url(
        meta.source_url
    ) or operavision.is_operavision_url(meta.detail_link):
        return False
    if metopera.is_metopera_url(meta.source_url) or metopera.is_metopera_url(
        meta.detail_link
    ):
        return False
    if broadwayhd.is_broadwayhd_url(meta.source_url) or broadwayhd.is_broadwayhd_url(
        meta.detail_link
    ):
        return False
    if is_ignored_metadata_value(label) or is_ignored_metadata_value(value):
        return False
    if is_technical_meta_key(label):
        return False
    return True


def looks_like_image_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    path = parsed.path.casefold()
    if not path:
        return False
    if any(path.endswith(ext) for ext in (".woff", ".woff2", ".css", ".js")):
        return False
    return bool(
        re.search(r"\.(?:jpg|jpeg|png|webp)(?:$|[._-])", path)
        or "_fmjpg_" in path
        or "_fmpng_" in path
    )


def clean_final_metadata(meta: Metadata) -> None:
    meta.genres = [value for value in dedupe_text(meta.genres) if not is_ignored_metadata_value(value)]
    meta.tags = [value for value in dedupe_text(meta.tags) if not is_ignored_metadata_value(value)]
    meta.studios = dedupe_text(meta.studios)
    meta.countries = dedupe_text(meta.countries)
    meta.directors = dedupe_text(meta.directors)
    meta.writers = dedupe_text(meta.writers)
    meta.credits = dedupe_text(meta.credits)

    if amazon.is_amazon_url(meta.source_url) or amazon.is_amazon_url(
        meta.detail_link
    ):
        meta.title = re.sub(r"^Watch\s+", "", meta.title, flags=re.IGNORECASE).strip()

    if meta.poster_url and not looks_like_image_url(meta.poster_url):
        meta.poster_url = ""
    if meta.fanart_url and not looks_like_image_url(meta.fanart_url):
        meta.fanart_url = ""
    if meta.logo_url and not looks_like_image_url(meta.logo_url):
        meta.logo_url = ""
    meta.gallery_urls = [url for url in dedupe_text(meta.gallery_urls) if looks_like_image_url(url)]


def dedupe_text(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        cleaned = clean_text(value)
        folded = cleaned.casefold()
        if cleaned and folded not in seen:
            output.append(cleaned)
            seen.add(folded)
    return output


def split_values(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, dict):
        return [clean_text(values)]
    if isinstance(values, (list, tuple, set)):
        output: list[str] = []
        for value in values:
            output.extend(split_values(value))
        return output

    text = clean_text(values)
    if not text:
        return []

    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", text):
        return [text]

    normalized = (
        text.replace("\u2022", ";")
        .replace("\u00b7", ";")
        .replace("|", ";")
        .replace("\n", ";")
    )
    if ";" in normalized:
        parts = normalized.split(";")
    elif "," in normalized and not re.search(r"\b\d{1,2},\s*\d{4}\b", normalized):
        parts = normalized.split(",")
    else:
        parts = [normalized]

    return [clean_text(part) for part in parts if clean_text(part)]


def parse_actors(values: Any) -> list[Actor]:
    if values is None:
        return []
    if isinstance(values, dict):
        name = clean_text(values.get("name") or values.get("@id"))
        role = clean_text(
            values.get("characterName")
            or values.get("roleName")
            or values.get("role")
            or values.get("jobTitle")
        )
        return [Actor(name=name, role=role)] if name else []
    if isinstance(values, (list, tuple, set)):
        actors: list[Actor] = []
        for value in values:
            actors.extend(parse_actors(value))
        return actors

    actors = []
    for part in split_values(values):
        role = ""
        name = part
        match = re.match(r"^(.+?)\s+(?:as|as:|role:)\s+(.+)$", part, flags=re.IGNORECASE)
        if not match:
            match = re.match(r"^(.+?)\s+-\s+(.+)$", part)
        if match:
            name = clean_text(match.group(1))
            role = clean_text(match.group(2))
        if name:
            actors.append(Actor(name=name, role=role))
    return actors


def normalize_label(label: str) -> str:
    text = clean_text(label).casefold()
    text = re.sub(r"[\s:：\-–—]+$", "", text)
    text = re.sub(r"^[\s:：\-–—]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_url(raw_url: str) -> str:
    text = clean_text(raw_url)
    if not text:
        return ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        return text
    possible_path = Path(text).expanduser()
    if possible_path.exists():
        return possible_path.resolve().as_uri()
    return "https://" + text


def fetch_html(url: str) -> tuple[str, str, list[str]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": ACCEPT_HEADER,
        },
    )
    warnings: list[str] = []
    try:
        html_text, final_url = read_html_response(request)
    except urllib.error.URLError as error:
        if not is_ssl_certificate_error(error):
            raise
        curl_result = fetch_html_with_curl(url)
        if curl_result:
            html_text, final_url = curl_result
            return html_text, final_url, warnings

        context = ssl._create_unverified_context()
        html_text, final_url = read_html_response(request, context=context)

    return html_text, final_url, warnings


def fetch_html_with_curl(url: str) -> tuple[str, str] | None:
    marker = "\n__MP3LI_FINAL_URL__:"
    command = [
        "/usr/bin/curl",
        "--location",
        "--silent",
        "--show-error",
        "--compressed",
        "--max-time",
        str(HTTP_TIMEOUT_SECONDS),
        "--user-agent",
        USER_AGENT,
        "--header",
        f"Accept: {ACCEPT_HEADER}",
        "--write-out",
        marker + "%{url_effective}",
        url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=HTTP_TIMEOUT_SECONDS + 5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None

    if result.returncode != 0 or marker not in result.stdout:
        return None
    html_text, final_url = result.stdout.rsplit(marker, 1)
    if not html_text.strip():
        return None
    return html_text, clean_text(final_url) or url


def read_html_response(
    request: urllib.request.Request, context: ssl.SSLContext | None = None
) -> tuple[str, str]:
    with urllib.request.urlopen(
        request, timeout=HTTP_TIMEOUT_SECONDS, context=context
    ) as response:
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        chunks = io.BytesIO()
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            chunks.write(chunk)
            if chunks.tell() > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(
                    f"Page is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB; stopping."
                )
        raw = chunks.getvalue()

    charset = charset_from_content_type(content_type) or charset_from_html_bytes(raw) or "utf-8"
    try:
        html_text = raw.decode(charset, errors="replace")
    except LookupError:
        html_text = raw.decode("utf-8", errors="replace")
    return html_text, final_url


def is_ssl_certificate_error(error: urllib.error.URLError) -> bool:
    reason = getattr(error, "reason", error)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    return "CERTIFICATE_VERIFY_FAILED" in str(error)


def charset_from_content_type(content_type: str) -> str:
    match = re.search(r"charset=([^\s;]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else ""


def charset_from_html_bytes(raw: bytes) -> str:
    head = raw[:4096].decode("ascii", errors="ignore")
    match = re.search(r"<meta[^>]+charset=[\"']?([^\s\"'>/;]+)", head, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def parse_detail_page(html_text: str, source_url: str, detail_link: str = "") -> Metadata:
    parser = DetailPageParser()
    parser.feed(html_text)

    meta = Metadata(source_url=source_url, detail_link=detail_link or source_url)
    apply_json_ld(meta, parser, source_url)
    apply_meta_tags(meta, parser, source_url)
    apply_visible_text(meta, parser)
    apply_amazon(meta, html_text, parser.visible_text)
    apply_operavision(meta, html_text, parser.visible_text)

    if not meta.title:
        for heading in parser.headings:
            if heading and len(heading) <= 180:
                meta.set_once("title", heading)
                break
    if not meta.title:
        meta.set_once("title", strip_site_suffix(parser.title))
    if not meta.title:
        parsed = urllib.parse.urlparse(source_url)
        meta.title = clean_text(Path(parsed.path).stem.replace("-", " ").replace("_", " ")) or parsed.netloc

    if meta.date and not meta.year:
        meta.year = extract_year(meta.date)

    clean_final_metadata(meta)
    meta.set_once("source_site", site_name_from_url(meta.source_url))
    detect_provider_ids(meta, source_url)
    return meta


def apply_amazon(meta: Metadata, html_text: str, visible_text: str) -> None:
    if not (
        amazon.is_amazon_url(meta.source_url)
        or amazon.is_amazon_url(meta.detail_link)
    ):
        return

    amazon_data = amazon.extract_metadata(
        html_text,
        visible_text,
        source_url=meta.source_url,
        detail_link=meta.detail_link,
    )
    if amazon_data.title:
        meta.title = amazon_data.title
    if amazon_data.plot:
        meta.plot = amazon_data.plot
    if amazon_data.tagline:
        meta.tagline = amazon_data.tagline
    if amazon_data.year:
        meta.year = amazon_data.year
    if amazon_data.runtime_minutes:
        meta.runtime_minutes = amazon_data.runtime_minutes
    if amazon_data.imdb_rating:
        meta.numeric_rating = amazon_data.imdb_rating
        meta.imdb_rating = amazon_data.imdb_rating
    if amazon_data.customer_rating:
        meta.amazon_rating = amazon_data.customer_rating
    if amazon_data.content_rating:
        meta.content_rating = amazon_data.content_rating
    if amazon_data.poster_url:
        meta.poster_url = amazon_data.poster_url
    if amazon_data.banner_url:
        meta.fanart_url = amazon_data.banner_url
    if amazon_data.trailer_url:
        meta.trailer_url = amazon_data.trailer_url
    if amazon_data.trailer_asset_id:
        meta.trailer_asset_id = amazon_data.trailer_asset_id
    if amazon_data.trailer_playback_id:
        meta.trailer_playback_id = amazon_data.trailer_playback_id
    if amazon_data.genres:
        meta.genres = amazon_data.genres
    if amazon_data.directors:
        meta.directors = amazon_data.directors
    if amazon_data.producers:
        meta.credits = amazon_data.producers
    if amazon_data.cast:
        meta.actors = [Actor(name=name) for name in amazon_data.cast]
    if amazon_data.studios:
        meta.studios = amazon_data.studios
        meta.production_label = "Studio"


def apply_operavision(meta: Metadata, html_text: str, visible_text: str) -> None:
    if not (
        operavision.is_operavision_url(meta.source_url)
        or operavision.is_operavision_url(meta.detail_link)
    ):
        return

    opera = operavision.extract_metadata(
        html_text,
        visible_text,
        source_url=meta.source_url,
        detail_link=meta.detail_link,
    )
    if opera.title:
        meta.title = opera.title
    if opera.tagline:
        meta.tagline = opera.tagline
    if opera.plot:
        meta.plot = opera.plot
    if opera.recorded_date:
        meta.date = opera.recorded_date
        meta.year = extract_year(opera.recorded_date)
    if opera.production:
        meta.studios = [opera.production]
        meta.production_label = "Production"
    if opera.composer:
        meta.add_values("credits", opera.composer)
        meta.add_extra("Composer", opera.composer)
    if opera.streamed_on:
        meta.add_extra("Streamed on", opera.streamed_on)
    if opera.available_until:
        meta.add_extra("Available until", opera.available_until)
    if opera.recorded_on:
        meta.add_extra("Recorded on", opera.recorded_on)
    if opera.poster_url:
        meta.poster_url = opera.poster_url
    if opera.wide_url:
        meta.fanart_url = opera.wide_url
    if opera.logo_url:
        meta.logo_url = opera.logo_url
    if opera.trailer_url:
        meta.trailer_url = opera.trailer_url
    if opera.cast:
        meta.actors = [
            Actor(name=name, role=role)
            for role, names in opera.cast
            for name in names
        ]
    for label, values in opera.crew.items():
        meta.add_extra(label, ", ".join(values))
        meta.add_values("credits", values)
    if opera.gallery_urls:
        meta.gallery_urls = opera.gallery_urls
        meta.add_extra("Gallery images found", str(len(opera.gallery_urls)))
    if opera.videos:
        meta.extra_videos = [
            ExtraMedia(
                title=video.title,
                kind=video.kind,
                description=video.description,
                url=video.url,
                page_url=video.page_url,
                external_url=video.external_url,
            )
            for video in opera.videos
        ]
        for video in opera.videos:
            label = f"Video - {video.kind}" if video.kind else "Video"
            value = video.title
            if video.description:
                value = f"{video.title}: {video.description}"
            meta.add_extra(label, value)
    meta.source_site = "OperaVision"


def metadata_from_metopera(url: str, detail_link: str = "") -> Metadata:
    opera = metopera.extract_metadata(url, timeout=HTTP_TIMEOUT_SECONDS)
    meta = Metadata(source_url=opera.source_url or url, detail_link=detail_link or url)
    meta.source_site = metopera.NAME
    meta.title = opera.title
    meta.outline = opera.plot or opera.brief_synopsis
    meta.plot = build_metopera_plot(opera)
    meta.date = opera.performance_date
    meta.year = extract_year(opera.performance_date)
    meta.runtime_minutes = opera.runtime_minutes
    meta.studios = [metopera.STUDIO_NAME]
    meta.production_label = "Provider"
    meta.poster_url = opera.poster_url
    meta.fanart_url = opera.wide_url
    meta.genres = opera.genres or ["Opera"]
    meta.tags = opera.tags
    meta.writers = opera.librettists
    meta.credits = dedupe_text(opera.composers + opera.conductors + opera.groups)
    meta.actors = [
        Actor(name=member.name, role=member.role)
        for member in opera.cast
        if member.credit_type == "ARTIST"
    ]

    if opera.met_id:
        meta.add_unique_id("metopera", opera.met_id)
    if opera.media_type:
        meta.add_extra("Media Type", opera.media_type)
    if opera.class_type:
        meta.add_extra("Class Type", opera.class_type)
    if opera.performance_date:
        meta.add_extra("Performance Date", opera.performance_date)
    if opera.start:
        meta.add_extra("Broadcast Start", opera.start)
    if opera.end:
        meta.add_extra("Broadcast End", opera.end)
    if opera.tier:
        meta.add_extra("Access Tier", opera.tier)
    if opera.item_id:
        meta.add_extra("Performance ID", opera.item_id)
    if opera.broadcast_id:
        meta.add_extra("Broadcast ID", opera.broadcast_id)
    if opera.met_id:
        meta.add_extra("Met Opera ID", opera.met_id)
    if opera.short_cast:
        meta.add_extra("Short Cast", opera.short_cast)
    if opera.full_synopsis_url:
        meta.add_extra("Full Synopsis URL", opera.full_synopsis_url)
    if opera.world_premiere:
        meta.add_extra("World Premiere", opera.world_premiere)
    if opera.subtitle_url:
        meta.add_extra("Possible Subtitle URL", opera.subtitle_url)
    if opera.composers:
        meta.add_extra("Composer", join_list(opera.composers))
    if opera.conductors:
        meta.add_extra("Conductor", join_list(opera.conductors))
    if opera.librettists:
        meta.add_extra("Librettist", join_list(opera.librettists))
    if opera.groups:
        meta.add_extra("Ensemble", join_list(opera.groups))
    if opera.tracks:
        meta.add_extra("Track Count", str(len(opera.tracks)))
    if opera.current_track:
        current = opera.current_track.title
        if opera.current_track.artists:
            current = f"{current} - {opera.current_track.artists}"
        meta.add_extra("Current Track", current)

    clean_final_metadata(meta)
    return meta


def metadata_from_broadwayhd(url: str, detail_link: str = "") -> Metadata:
    bway = broadwayhd.extract_metadata(url, timeout=HTTP_TIMEOUT_SECONDS)
    meta = Metadata(source_url=bway.source_url or url, detail_link=detail_link or url)
    meta.source_site = broadwayhd.NAME
    meta.title = bway.title
    meta.plot = bway.plot
    meta.year = bway.year
    meta.runtime_minutes = bway.runtime_minutes
    meta.studios = [broadwayhd.STUDIO_NAME]
    meta.production_label = "Provider"
    meta.poster_url = bway.poster_url
    meta.fanart_url = bway.wide_url
    meta.logo_url = bway.logo_url
    meta.trailer_url = bway.trailer_url
    meta.genres = bway.genres
    meta.directors = dedupe_text(bway.directors + bway.film_directors)
    meta.writers = bway.writers
    meta.credits = dedupe_text(
        bway.music_and_lyrics + bway.producers + bway.executive_producers
    )
    meta.actors = [Actor(name=name) for name in bway.cast]

    if bway.item_id:
        meta.add_unique_id("broadwayhd", bway.item_id)
    if bway.film_directors:
        meta.add_extra("Film Director", join_list(bway.film_directors))
    if bway.writers:
        meta.add_extra("Book", join_list(bway.writers))
    if bway.music_and_lyrics:
        meta.add_extra("Music & Lyrics", join_list(bway.music_and_lyrics))
    if bway.producers:
        meta.add_extra("Producer", join_list(bway.producers))
    if bway.executive_producers:
        meta.add_extra("Executive Producer", join_list(bway.executive_producers))

    clean_final_metadata(meta)
    return meta


def build_metopera_plot(opera: metopera.MetOperaMetadata) -> str:
    pieces: list[str] = []
    short_description = opera.plot or opera.brief_synopsis
    if short_description:
        pieces.append(short_description)
    if opera.full_synopsis:
        pieces.append("Full Synopsis:\n\n" + opera.full_synopsis)
    if opera.world_premiere:
        pieces.append(opera.world_premiere)
    return "\n\n".join(pieces)


def apply_json_ld(meta: Metadata, parser: DetailPageParser, source_url: str) -> None:
    objects: list[dict[str, Any]] = []
    for script in parser.json_ld_scripts:
        for data in load_json_ld(script):
            objects.extend(iter_json_ld_objects(data))

    for obj in objects:
        if not isinstance(obj, dict):
            continue
        type_text = " ".join(split_values(obj.get("@type"))).casefold()
        if "website" in type_text:
            meta.set_once("source_site", obj.get("name"))

    ranked = sorted(
        (obj for obj in objects if isinstance(obj, dict)),
        key=json_ld_score,
        reverse=True,
    )

    for index, obj in enumerate(ranked):
        if json_ld_score(obj) <= 0:
            continue
        apply_json_ld_object(meta, obj, source_url, primary=index == 0)


def load_json_ld(script: str) -> list[Any]:
    cleaned = script.strip()
    if not cleaned:
        return []
    cleaned = re.sub(r"^<!--|-->$", "", cleaned).strip()
    candidates = [cleaned, re.sub(r",\s*([}\]])", r"\1", cleaned)]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            continue
    return []


def iter_json_ld_objects(data: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            found.extend(iter_json_ld_objects(item))
    elif isinstance(data, dict):
        found.append(data)
        for key in (
            "@graph",
            "mainEntity",
            "video",
            "subjectOf",
            "workPerformed",
            "about",
            "itemReviewed",
        ):
            if key in data:
                found.extend(iter_json_ld_objects(data[key]))
    return found


def json_ld_score(obj: dict[str, Any]) -> int:
    type_text = " ".join(split_values(obj.get("@type"))).casefold()
    score = 0
    if any(
        item in type_text
        for item in (
            "videoobject",
            "movie",
            "tvepisode",
            "episode",
            "musicvideoobject",
            "event",
            "creativework",
        )
    ):
        score += 30
    if obj.get("name") or obj.get("headline"):
        score += 5
    if obj.get("description"):
        score += 5
    if obj.get("actor") or obj.get("performer") or obj.get("director"):
        score += 5
    if "breadcrumblist" in type_text or "webpage" in type_text or "website" in type_text:
        score -= 25
    return score


def apply_json_ld_object(
    meta: Metadata, obj: dict[str, Any], source_url: str, primary: bool = False
) -> None:
    if primary:
        meta.set_once("title", obj.get("name") or obj.get("headline"))
        meta.set_once("original_title", obj.get("alternateName"))
        meta.set_once("plot", obj.get("description"))

    date_value = (
        obj.get("datePublished")
        or obj.get("releaseDate")
        or obj.get("uploadDate")
        or obj.get("startDate")
        or obj.get("dateCreated")
    )
    apply_date(meta, date_value)

    duration = parse_runtime(obj.get("duration"))
    if duration:
        meta.set_once("runtime_minutes", duration)

    meta.add_values("genres", obj.get("genre"))
    meta.add_values("tags", obj.get("keywords"))
    meta.set_once("content_rating", obj.get("contentRating"))
    meta.set_once("language", obj.get("inLanguage"))
    meta.add_values("countries", obj.get("countryOfOrigin") or obj.get("locationCreated"))
    meta.add_values("studios", obj.get("productionCompany") or obj.get("publisher"))
    meta.add_values("directors", obj.get("director"))
    meta.add_values("writers", obj.get("writer") or obj.get("author"))
    meta.add_values("credits", obj.get("creator") or obj.get("producer"))
    meta.add_actors(obj.get("actor") or obj.get("performer") or obj.get("cast"))

    image = first_url(obj.get("image") or obj.get("thumbnailUrl"), source_url)
    if image:
        meta.set_once("poster_url", image)

    numeric_rating = extract_rating(obj.get("aggregateRating") or obj.get("reviewRating"))
    if numeric_rating:
        meta.set_once("numeric_rating", numeric_rating)

    for possible_url in split_values(obj.get("url")) + split_values(obj.get("sameAs")):
        detect_provider_ids(meta, urllib.parse.urljoin(source_url, possible_url))

    type_text = clean_text(obj.get("@type"))
    if type_text:
        meta.add_extra("JSON-LD type", type_text)

    for key in (
        "location",
        "organizer",
        "provider",
        "copyrightHolder",
        "isFamilyFriendly",
    ):
        if key in obj:
            meta.add_extra(f"JSON-LD {key}", obj[key])


def apply_meta_tags(meta: Metadata, parser: DetailPageParser, source_url: str) -> None:
    canonical = ""
    for link in parser.link_tags:
        rel = link.get("rel", "").casefold()
        href = link.get("href", "")
        if "canonical" in rel and href:
            canonical = urllib.parse.urljoin(source_url, href)
        elif "image_src" in rel and href:
            meta.set_once("poster_url", urllib.parse.urljoin(source_url, href))
    if canonical:
        meta.source_url = canonical

    for tag in parser.meta_tags:
        key = (
            tag.get("property")
            or tag.get("name")
            or tag.get("itemprop")
            or tag.get("http-equiv")
            or ""
        )
        key = key.strip()
        key_lower = key.casefold()
        content = tag.get("content") or tag.get("value") or ""
        if not key or not content:
            continue

        if key_lower in {"og:title", "twitter:title", "title"}:
            meta.set_once("title", strip_site_suffix(content))
        elif key_lower in {"og:description", "twitter:description", "description"}:
            meta.set_once("plot", content)
        elif key_lower in {"og:image", "twitter:image", "image", "thumbnail", "thumbnailurl"}:
            meta.set_once("poster_url", urllib.parse.urljoin(source_url, content))
        elif key_lower in {"og:url"}:
            meta.source_url = urllib.parse.urljoin(source_url, content)
        elif key_lower in {
            "article:published_time",
            "video:release_date",
            "release_date",
            "date",
            "pubdate",
            "dc.date",
            "dcterms.date",
        }:
            apply_date(meta, content)
        elif key_lower in {"video:duration", "duration"}:
            runtime = parse_runtime(content)
            if runtime:
                meta.set_once("runtime_minutes", runtime)
        elif key_lower in {"keywords", "article:tag", "news_keywords"}:
            meta.add_values("tags", content)
        elif key_lower in {"og:site_name", "application-name"}:
            meta.set_once("source_site", content)
        elif is_technical_meta_key(key_lower):
            continue
        else:
            meta.add_extra(f"meta {key}", content)

    detect_provider_ids(meta, meta.source_url)


def apply_visible_text(meta: Metadata, parser: DetailPageParser) -> None:
    lines = [
        line.strip(" \t-:")
        for line in parser.visible_text.splitlines()
        if line.strip(" \t-:")
    ]

    for line in lines:
        match = re.match(r"^([^:]{2,55})\s*[:：]\s*(.{1,500})$", line)
        if match:
            process_labeled_field(meta, match.group(1), match.group(2))
            continue
        match = re.match(r"^(.{2,55})\s+[–—-]\s+(.{1,500})$", line)
        if match and normalize_label(match.group(1)) in LABEL_MAP:
            process_labeled_field(meta, match.group(1), match.group(2))

    for index, line in enumerate(lines[:-1]):
        normalized = normalize_label(line)
        if normalized not in LABEL_MAP:
            continue
        value = lines[index + 1]
        if normalize_label(value) in LABEL_MAP:
            continue
        if len(value) > 700:
            continue
        process_labeled_field(meta, line, value)


def process_labeled_field(meta: Metadata, label: str, value: str) -> None:
    normalized = normalize_label(label)
    mapped = LABEL_MAP.get(normalized)
    if not mapped:
        if should_keep_unmapped_visible_field(meta, label, value):
            meta.add_extra(label, value)
        return

    if mapped == "title":
        meta.set_once("title", value)
    elif mapped == "plot":
        meta.set_once("plot", value)
    elif mapped == "tagline":
        meta.set_once("tagline", value)
    elif mapped == "date":
        apply_date(meta, value)
    elif mapped == "runtime":
        runtime = parse_runtime(value)
        if runtime:
            meta.set_once("runtime_minutes", runtime)
    elif mapped == "content_rating":
        meta.set_once("content_rating", value)
    elif mapped == "rating":
        rating = extract_rating(value)
        if rating:
            meta.set_once("numeric_rating", rating)
        else:
            meta.set_once("content_rating", value)
    elif mapped == "language":
        meta.set_once("language", value)
    elif mapped == "genre":
        meta.add_values("genres", value)
    elif mapped == "tag":
        meta.add_values("tags", value)
    elif mapped == "studio":
        meta.add_values("studios", value)
    elif mapped == "country":
        meta.add_values("countries", value)
    elif mapped == "director":
        meta.add_values("directors", value)
    elif mapped == "writer":
        meta.add_values("writers", value)
    elif mapped == "credits":
        meta.add_values("credits", value)
    elif mapped == "cast":
        meta.add_actors(value)
    elif mapped == "location":
        meta.add_extra("Location", value)


def apply_date(meta: Metadata, value: Any) -> None:
    date = normalize_date(value)
    if date:
        meta.set_once("date", date)
        year = extract_year(date)
        if year:
            meta.set_once("year", year)
    elif clean_text(value):
        meta.add_extra("Unparsed date", value)


def normalize_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""

    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        return match.group(0)

    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if match:
        month, day, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    match = re.search(
        r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b", text
    )
    if match:
        month = MONTHS.get(match.group(1).casefold())
        day = int(match.group(2))
        year = int(match.group(3))
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)[,]?\s+(\d{4})\b", text
    )
    if match:
        day = int(match.group(1))
        month = MONTHS.get(match.group(2).casefold())
        year = int(match.group(3))
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    year = extract_year(text)
    return year


def extract_year(value: Any) -> str:
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", clean_text(value))
    return match.group(1) if match else ""


def parse_runtime(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""

    match = re.match(
        r"^P(?:T)?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", text, flags=re.IGNORECASE
    )
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        total = hours * 60 + minutes + (1 if seconds >= 30 else 0)
        return str(total) if total else ""

    match = re.search(
        r"\b(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?\s*(?:(\d+)\s*s(?:ec(?:ond)?s?)?)?\b",
        text,
        flags=re.IGNORECASE,
    )
    if match and (match.group(1) or match.group(2) or match.group(3)):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        total = hours * 60 + minutes + (1 if seconds >= 30 else 0)
        return str(total) if total else ""

    match = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", text)
    if match:
        first = int(match.group(1))
        second = int(match.group(2))
        third = int(match.group(3) or 0)
        if match.group(3):
            total = first * 60 + second + (1 if third >= 30 else 0)
        else:
            total = first * 60 + second
        return str(total) if total else ""

    match = re.search(r"\b(\d{1,5})\s*(?:minutes?|mins?|m)\b", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)

    if text.isdigit():
        number = int(text)
        if number > 300:
            return str(round(number / 60))
        return str(number)

    return ""


def extract_rating(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("ratingValue") or value.get("value") or value.get("rating")
    text = clean_text(value)
    if not text:
        return ""
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\b", text)
    if match:
        numerator = float(match.group(1))
        denominator = float(match.group(2))
        if denominator:
            return f"{numerator / denominator * 10:.1f}".rstrip("0").rstrip(".")
    match = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    if match:
        number = float(match.group(1))
        if number <= 10:
            return f"{number:.1f}".rstrip("0").rstrip(".")
        if number <= 100:
            return f"{number / 10:.1f}".rstrip("0").rstrip(".")
    return ""


def first_url(value: Any, base_url: str) -> str:
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    for candidate in split_values(value):
        if candidate:
            return urllib.parse.urljoin(base_url, candidate)
    return ""


def detect_provider_ids(meta: Metadata, url: str) -> None:
    text = clean_text(url)
    if not text:
        return
    match = re.search(r"\b(tt\d{7,10})\b", text)
    if match:
        meta.add_unique_id("imdb", match.group(1))
    match = re.search(r"themoviedb\.org/(?:movie|tv)/(\d+)", text, flags=re.IGNORECASE)
    if match:
        meta.add_unique_id("tmdb", match.group(1))
    match = re.search(r"thetvdb\.com/.+?/(\d+)", text, flags=re.IGNORECASE)
    if match:
        meta.add_unique_id("tvdb", match.group(1))


def site_name_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(clean_text(url))
    host = parsed.netloc.casefold()
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def strip_site_suffix(title: Any) -> str:
    text = clean_text(title)
    if not text:
        return ""
    for separator in (" | ", " - ", " :: "):
        parts = [part.strip() for part in text.split(separator) if part.strip()]
        if len(parts) >= 2 and len(parts[0]) >= 3:
            return parts[0]
    return text


def build_nfo_xml(meta: Metadata) -> str:
    root = ET.Element("movie")

    add_text(root, "title", meta.title)
    add_text(root, "originaltitle", meta.original_title)
    add_text(root, "sorttitle", meta.sort_title)
    add_text(root, "outline", meta.outline)
    add_text(root, "plot", meta.plot)
    add_text(root, "tagline", meta.tagline)
    add_text(root, "year", meta.year)
    add_text(root, "premiered", meta.date)
    add_text(root, "aired", meta.date)
    add_text(root, "releasedate", meta.date)
    add_text(root, "runtime", meta.runtime_minutes)
    add_text(root, "rating", meta.numeric_rating)
    add_text(root, "imdbrating", meta.imdb_rating)
    add_text(root, "amazonrating", meta.amazon_rating)
    add_text(root, "mpaa", meta.content_rating)
    add_text(root, "customrating", meta.content_rating)
    add_text(root, "language", meta.language)
    add_text(root, "source_site", meta.source_site)
    add_text(root, "detail_link", meta.detail_link)
    add_text(root, "source_url", meta.source_url)

    for country in meta.countries:
        add_text(root, "country", country)
    for genre in meta.genres:
        add_text(root, "genre", genre)
    for tag in meta.tags:
        add_text(root, "tag", tag)
    for studio in meta.studios:
        add_text(root, "studio", studio)
    for director in meta.directors:
        add_text(root, "director", director)
    for writer in meta.writers:
        add_text(root, "writer", writer)
    for credit in meta.credits:
        add_text(root, "credits", credit)

    for index, (provider, value) in enumerate(meta.unique_ids.items()):
        unique_id = ET.SubElement(root, "uniqueid")
        unique_id.set("type", provider)
        if index == 0:
            unique_id.set("default", "true")
        unique_id.text = value
        if provider in {"imdb", "tmdb", "tvdb"}:
            add_text(root, f"{provider}id", value)

    for actor in meta.actors:
        actor_element = ET.SubElement(root, "actor")
        add_text(actor_element, "name", actor.name)
        add_text(actor_element, "role", actor.role)

    add_text(root, "dateadded", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    if meta.source_site:
        root.append(ET.Comment(f" Source site: {sanitize_xml_comment(meta.source_site)} "))
    if meta.detail_link:
        root.append(ET.Comment(f" Detail link given: {sanitize_xml_comment(meta.detail_link)} "))
    root.append(ET.Comment(f" Source URL: {sanitize_xml_comment(meta.source_url)} "))
    root.append(ET.Comment(" Generated by Live Performance Metadata and Extras Getter by mp3li "))

    extra_comment = build_extra_comment(meta)
    if extra_comment:
        root.append(ET.Comment(extra_comment))

    if hasattr(ET, "indent"):
        ET.indent(root, space="  ")
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml_body + "\n"


def add_text(parent: ET.Element, tag: str, value: Any) -> None:
    if tag == "plot":
        text = clean_text_preserving_lines("" if value is None else str(value))
    else:
        text = clean_text(value)
    if text:
        ET.SubElement(parent, tag).text = text


def build_extra_comment(meta: Metadata) -> str:
    lines = ["", "Additional scraped fields:"]
    for label in sorted(meta.extra_fields, key=str.casefold):
        values = meta.extra_fields[label]
        for value in values:
            lines.append(f"{label}: {value}")
    if len(lines) == 1:
        return ""
    return sanitize_xml_comment("\n".join(lines) + "\n")


def sanitize_xml_comment(text: str) -> str:
    return clean_text_preserving_lines(text).replace("--", "- -").replace("\u0000", "")


def safe_filename(name: str) -> str:
    cleaned = clean_text(name)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned[:120].strip(" .")
    return cleaned or "metadata"


def output_path_for_filename_base(output_dir: Path, filename_base: str) -> Path:
    return output_dir / f"{safe_filename(filename_base)}.nfo"


def metadata_bundle_name(meta: Metadata) -> str:
    title = safe_filename(meta.title)
    production_or_studio = safe_filename(first_production_or_studio(meta))
    if production_or_studio:
        return safe_filename(f"{title} - {production_or_studio}")
    return title


def output_folder_for_metadata(output_dir: Path, meta: Metadata) -> Path:
    return output_dir / metadata_bundle_name(meta)


def first_production_or_studio(meta: Metadata) -> str:
    if meta.studios:
        return meta.studios[0]
    return ""


def is_supported_trailer_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    if parsed.scheme not in {"http", "https"}:
        return False
    return parsed.path.casefold().endswith(".mp4")


def download_assets_for_metadata(meta: Metadata, output_dir: Path, filename_base: str) -> list[Path]:
    saved_items: list[Path] = []
    base = safe_filename(filename_base)
    poster_path = maybe_download_image_asset(
        meta.poster_url, output_dir / f"{base}-poster", "cover art"
    )
    if poster_path:
        meta.local_poster_path = poster_path.name
        saved_items.append(poster_path)

    wide_art_paths = download_wide_image_variants(meta.fanart_url, output_dir, base)
    if wide_art_paths:
        meta.local_fanart_path = wide_art_paths[0].name
        saved_items.extend(wide_art_paths)

    logo_path = maybe_download_image_asset(
        meta.logo_url, output_dir / f"{base}-logo", "logo"
    )
    if logo_path:
        meta.local_logo_path = logo_path.name
        saved_items.append(logo_path)

    trailer_url = resolve_direct_trailer_url(meta)
    if trailer_url:
        meta.trailer_url = trailer_url
        trailer_path = download_direct_trailer(trailer_url, output_dir / "trailers" / "trailer.mp4")
        if trailer_path:
            meta.local_trailer_path = trailer_path.relative_to(output_dir).as_posix()
            saved_items.append(trailer_path)
    saved_items.extend(download_extra_sections_for_metadata(meta, output_dir, base))
    return saved_items


def download_extra_sections_for_metadata(meta: Metadata, output_dir: Path, base: str) -> list[Path]:
    saved_items: list[Path] = []
    if meta.gallery_urls:
        gallery_dir = output_dir / "extras" / "gallery"
        for index, url in enumerate(meta.gallery_urls, start=1):
            gallery_path = maybe_download_image_asset(
                url,
                gallery_dir / f"{base}-gallery-{index:02d}",
                f"gallery image {index}",
            )
            if gallery_path:
                saved_items.append(gallery_path)

    if meta.extra_videos:
        video_dir = output_dir / "extras" / "videos"
        for index, video in enumerate(meta.extra_videos, start=1):
            if is_duplicate_trailer_extra_video(meta, video):
                continue
            label = video.kind or f"video {index}"
            video_base = safe_filename(video.title or f"{base}-video-{index:02d}")
            external_url = video.external_url or video.page_url
            if external_url:
                extra_path = download_external_video_as_mp4(
                    external_url,
                    video_dir / f"{video_base}.mp4",
                )
                if extra_path:
                    saved_items.append(extra_path)
                continue

            if video.url and is_supported_trailer_url(video.url):
                video_path = video_dir / f"{video_base}.mp4"
                existing_trailer = (
                    output_dir / meta.local_trailer_path
                    if meta.local_trailer_path and video.url == meta.trailer_url
                    else None
                )
                extra_path = copy_or_download_direct_video(
                    video.url,
                    video_path,
                    label,
                    existing_trailer,
                )
                if extra_path:
                    saved_items.append(extra_path)
                continue
    return saved_items


def is_duplicate_trailer_extra_video(meta: Metadata, video: ExtraMedia) -> bool:
    return bool(
        meta.trailer_url
        and video.url == meta.trailer_url
        and not (video.external_url or video.page_url)
    )


def download_external_video_as_mp4(url: str, path: Path) -> Path | None:
    command_prefix = ytdlp_command()
    if not command_prefix:
        return None
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        with tempfile.TemporaryDirectory(prefix=".yt-dlp-", dir=path.parent) as temp_dir:
            output_template = str(Path(temp_dir) / "video.%(ext)s")
            command = [
                *command_prefix,
                "--no-playlist",
                "--retries",
                "10",
                "--fragment-retries",
                "10",
                "--retry-sleep",
                "linear=1::5",
                "--socket-timeout",
                "30",
                "--format",
                "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best[ext=mp4]/best",
                "--merge-output-format",
                "mp4",
                "--recode-video",
                "mp4",
                "--output",
                output_template,
                url,
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=EXTERNAL_VIDEO_DOWNLOAD_TIMEOUT_SECONDS,
                )
            except (FileNotFoundError, subprocess.SubprocessError, TimeoutError):
                result = None
            if result and result.returncode == 0:
                mp4_candidates = sorted(Path(temp_dir).glob("*.mp4"))
                if mp4_candidates:
                    shutil.move(str(mp4_candidates[0]), str(path))
                    return path
        if attempt < 2:
            time.sleep(2)
    return None


def ytdlp_command() -> list[str]:
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    return []


def download_wide_image_variants(url: str, output_dir: Path, base: str) -> list[Path]:
    fanart_path = maybe_download_image_asset(
        url, output_dir / f"{base}-fanart", "wide art/fanart"
    )
    if not fanart_path:
        return []

    saved_paths = [fanart_path]
    for suffix in WIDE_ART_SUFFIXES[1:]:
        variant_path = fanart_path.with_name(f"{base}-{suffix}{fanart_path.suffix}")
        if variant_path.exists():
            saved_paths.append(variant_path)
            continue
        try:
            shutil.copyfile(fanart_path, variant_path)
        except OSError as error:
            continue
        saved_paths.append(variant_path)
    return saved_paths


def maybe_download_image_asset(url: str, output_base: Path, label: str) -> Path | None:
    if not url or not looks_like_image_url(url):
        return None
    extension = image_extension_from_url(url) or ".jpg"
    path = output_base.with_suffix(extension)
    if path.exists():
        return path
    try:
        download_url_to_file(url, path, max_bytes=30 * 1024 * 1024)
    except RuntimeError:
        return None
    return path


def download_direct_trailer(url: str, path: Path) -> Path | None:
    if not is_supported_trailer_url(url):
        return None
    if path.exists():
        return path
    try:
        download_url_to_file(url, path, max_bytes=350 * 1024 * 1024, timeout=180)
    except RuntimeError:
        return None
    return path


def copy_or_download_direct_video(
    url: str, path: Path, label: str, existing_source: Path | None = None
) -> Path | None:
    if not is_supported_trailer_url(url):
        return None
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if existing_source and existing_source.exists():
        try:
            shutil.copyfile(existing_source, path)
        except OSError:
            return None
        return path
    try:
        download_url_to_file(url, path, max_bytes=350 * 1024 * 1024, timeout=180)
    except RuntimeError:
        return None
    return path


def resolve_direct_trailer_url(meta: Metadata) -> str:
    if is_supported_trailer_url(meta.trailer_url):
        return meta.trailer_url
    if not meta.trailer_url:
        return ""

    try:
        html_text, _final_url, warnings = fetch_html(meta.trailer_url)
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as error:
        return ""

    meta.warnings.extend(warnings)
    direct_url = amazon.find_direct_trailer_media_url(html_text)
    if direct_url and is_supported_trailer_url(direct_url):
        return direct_url

    direct_url = capture_direct_trailer_url_with_chrome(meta.trailer_url)
    if direct_url:
        return direct_url

    return ""


def capture_direct_trailer_url_with_chrome(url: str) -> str:
    if not CHROME_APP_PATH.exists():
        return ""

    with tempfile.TemporaryDirectory(dir="/private/tmp") as profile_dir:
        profile_path = Path(profile_dir)
        command = [
            str(CHROME_APP_PATH),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile_path}",
            f"--user-agent={USER_AGENT}",
            "about:blank",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            port = wait_for_chrome_debugging_port(profile_path, process)
            if not port:
                return ""
            websocket_url = create_chrome_devtools_page(port)
            if not websocket_url:
                return ""
            return watch_chrome_network_for_trailer(websocket_url, url)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def wait_for_chrome_debugging_port(profile_path: Path, process: subprocess.Popen) -> int:
    active_port_path = profile_path / "DevToolsActivePort"
    deadline = time.time() + 10
    while time.time() < deadline:
        if process.poll() is not None:
            return 0
        if active_port_path.exists():
            lines = active_port_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if lines and lines[0].isdigit():
                return int(lines[0])
        time.sleep(0.1)
    return 0


def create_chrome_devtools_page(port: int) -> str:
    for method in ("PUT", "GET"):
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/json/new",
                method=method,
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            websocket_url = data.get("webSocketDebuggerUrl", "")
            if websocket_url:
                return websocket_url
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
            pages = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return ""
    for page in pages:
        websocket_url = page.get("webSocketDebuggerUrl", "")
        if websocket_url:
            return websocket_url
    return ""


def watch_chrome_network_for_trailer(websocket_url: str, trailer_page_url: str) -> str:
    websocket = DevToolsWebSocket(websocket_url)
    websocket.connect()
    try:
        next_id = 1
        for method, params in (
            ("Network.enable", {}),
            ("Page.enable", {}),
            (
                "Network.setUserAgentOverride",
                {
                    "userAgent": USER_AGENT,
                    "acceptLanguage": "en-US,en;q=0.9",
                    "platform": "MacIntel",
                },
            ),
            ("Page.navigate", {"url": trailer_page_url}),
        ):
            websocket.send_json({"id": next_id, "method": method, "params": params})
            next_id += 1

        deadline = time.time() + TRAILER_CAPTURE_TIMEOUT_SECONDS
        clicked = False
        while time.time() < deadline:
            if not clicked and time.time() < deadline - 5:
                websocket.send_json(
                    {
                        "id": next_id,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": (
                                "Array.from(document.querySelectorAll('button,[role=button]'))"
                                ".find(b => /trailer/i.test(b.innerText || b.ariaLabel || ''))?.click()"
                            ),
                        },
                    }
                )
                next_id += 1
                clicked = True

            message = websocket.recv_json(timeout=1)
            if not message:
                continue
            for candidate in direct_trailer_candidates_from_cdp_message(message):
                if is_supported_trailer_url(candidate):
                    return candidate
        return ""
    finally:
        websocket.close()


def direct_trailer_candidates_from_cdp_message(message: dict[str, Any]) -> list[str]:
    method = message.get("method", "")
    params = message.get("params", {})
    candidates: list[str] = []
    if method == "Network.requestWillBeSent":
        request = params.get("request", {})
        candidates.append(request.get("url", ""))
    elif method == "Network.responseReceived":
        response = params.get("response", {})
        candidates.append(response.get("url", ""))
    elif method == "Network.responseReceivedExtraInfo":
        candidates.append(params.get("url", ""))
    return [candidate for candidate in candidates if candidate]


class DevToolsWebSocket:
    def __init__(self, websocket_url: str) -> None:
        parsed = urllib.parse.urlparse(websocket_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path
        if parsed.query:
            self.path += "?" + parsed.query
        self.sock: socket.socket | None = None

    def connect(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        sock = socket.create_connection((self.host, self.port), timeout=10)
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            sock.close()
            raise RuntimeError("Chrome DevTools WebSocket handshake failed.")
        self.sock = sock

    def send_json(self, payload: dict[str, Any]) -> None:
        self.send_text(json.dumps(payload, separators=(",", ":")))

    def send_text(self, text: str) -> None:
        if not self.sock:
            return
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.extend([0x80 | 126])
            header.extend(struct.pack("!H", length))
        else:
            header.extend([0x80 | 127])
            header.extend(struct.pack("!Q", length))
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_json(self, timeout: float = 1) -> dict[str, Any] | None:
        text = self.recv_text(timeout=timeout)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def recv_text(self, timeout: float = 1) -> str:
        if not self.sock:
            return ""
        self.sock.settimeout(timeout)
        try:
            first_two = self.read_exact(2)
        except (TimeoutError, socket.timeout):
            return ""
        if len(first_two) < 2:
            return ""
        opcode = first_two[0] & 0x0F
        masked = bool(first_two[1] & 0x80)
        length = first_two[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.read_exact(8))[0]
        mask = self.read_exact(4) if masked else b""
        payload = self.read_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 8:
            return ""
        if opcode == 9:
            return ""
        if opcode != 1:
            return ""
        return payload.decode("utf-8", errors="replace")

    def read_exact(self, size: int) -> bytes:
        if not self.sock:
            return b""
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        return bytes(chunks)

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None


def image_extension_from_url(url: str) -> str:
    path = urllib.parse.urlparse(clean_text(url)).path.casefold()
    for extension in (".jpg", ".jpeg", ".png", ".webp"):
        if extension in path:
            return ".jpg" if extension == ".jpeg" else extension
    return ""


def download_url_to_file(
    url: str, path: Path, max_bytes: int, timeout: int = HTTP_TIMEOUT_SECONDS
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".download")
    if temp_path.exists():
        temp_path.unlink()

    try:
        download_url_to_file_with_urllib(url, temp_path, max_bytes=max_bytes, timeout=timeout)
    except RuntimeError as urllib_error:
        try:
            download_url_to_file_with_curl(url, temp_path, max_bytes=max_bytes, timeout=timeout)
        except RuntimeError as curl_error:
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(f"{urllib_error}; curl fallback also failed: {curl_error}") from curl_error

    temp_path.replace(path)


def download_url_to_file_with_urllib(
    url: str, path: Path, max_bytes: int, timeout: int
) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            write_response_stream(response, path, max_bytes)
    except urllib.error.URLError as error:
        raise RuntimeError(str(error)) from error
    except TimeoutError as error:
        raise RuntimeError(str(error)) from error


def write_response_stream(response: Any, path: Path, max_bytes: int) -> None:
    total = 0
    with path.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError(f"download exceeded {max_bytes // (1024 * 1024)} MB limit")
            output.write(chunk)


def download_url_to_file_with_curl(
    url: str, path: Path, max_bytes: int, timeout: int
) -> None:
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
        "--output",
        str(path),
        url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout + 10,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        raise RuntimeError(str(error)) from error
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exited with {result.returncode}")


def write_nfo(meta: Metadata, item_output_dir: Path, filename_base: str = "") -> Path:
    item_output_dir.mkdir(parents=True, exist_ok=True)
    path = output_path_for_filename_base(item_output_dir, filename_base or meta.title)
    path.write_text(build_nfo_xml(meta), encoding="utf-8")
    return path


def save_title_folder(meta: Metadata, output_dir: Path) -> SaveResult | None:
    filename_base = metadata_bundle_name(meta)
    item_output_dir = output_folder_for_metadata(output_dir, meta)
    item_output_dir.mkdir(parents=True, exist_ok=True)
    path = output_path_for_filename_base(item_output_dir, filename_base)
    if path.exists() and not ask_yes_no(
        f"{path.name} already exists in this title folder. Overwrite it?", default=False
    ):
        print(f"Skipped existing file: {path}")
        return None
    with AnimatedStatus("Creating your .nfo file and grabbing your trailer/images"):
        items = download_assets_for_metadata(meta, item_output_dir, filename_base)
        nfo_path = write_nfo(meta, item_output_dir, filename_base)
    return SaveResult(folder=item_output_dir, items=[nfo_path, *items])


def format_preview(meta: Metadata) -> str:
    rows = [
        ("Source Site", meta.source_site),
        ("Detail Link Given", meta.detail_link),
        ("Fetched/Canonical URL", meta.source_url),
        ("Title", meta.title),
        ("Tagline", meta.tagline),
        ("Outline", meta.outline),
        ("Date", meta.date),
        ("Year", meta.year),
        ("Runtime", f"{meta.runtime_minutes} minutes" if meta.runtime_minutes else ""),
        ("IMDb Rating", meta.imdb_rating or meta.numeric_rating),
        ("Amazon Rating", meta.amazon_rating),
        ("Content Rating", meta.content_rating),
        ("Language", meta.language),
        (meta.production_label, join_list(meta.studios)),
        ("Country", join_list(meta.countries)),
        ("Genre", join_list(meta.genres)),
        ("Tags", join_list(meta.tags)),
        ("Director", join_list(meta.directors)),
        ("Writer", join_list(meta.writers)),
        ("Credits/Producer", join_list(meta.credits)),
        ("Cast", format_cast(meta.actors)),
        ("Cover Art", found_status(meta.poster_url)),
        ("Wide Art", wide_art_status(meta.fanart_url)),
        ("Logo", found_status(meta.logo_url)),
        ("Gallery", count_status(meta.gallery_urls, "image")),
        ("Extra Videos", extra_video_status(meta)),
        ("Trailer", found_status(meta.trailer_url)),
        ("Plot", meta.plot),
    ]
    output = ["-" * 72]
    for label, value in rows:
        if value:
            output.extend(wrap_row(label, value))

    if meta.extra_fields:
        output.append("")
        output.append("Additional scraped fields:")
        for label in sorted(meta.extra_fields, key=str.casefold):
            for value in meta.extra_fields[label]:
                output.extend(wrap_row(label, value))

    if meta.warnings:
        output.append("")
        output.append("Warnings:")
        output.extend(f"- {warning}" for warning in meta.warnings)

    output.append("-" * 72)
    return "\n".join(output)


def found_status(value: str) -> str:
    return "found" if clean_text(value) else ""


def wide_art_status(value: str) -> str:
    if not clean_text(value):
        return ""
    return "found (fanart, banner, landscape)"


def count_status(values: list[Any], label: str) -> str:
    count = len(values)
    if not count:
        return ""
    noun = label if count == 1 else f"{label}s"
    return f"found ({count} {noun})"


def extra_video_status(meta: Metadata) -> str:
    videos = [
        video for video in meta.extra_videos if not is_duplicate_trailer_extra_video(meta, video)
    ]
    if not videos:
        return ""
    direct_count = sum(1 for video in videos if is_supported_trailer_url(video.url))
    embedded_count = sum(
        1
        for video in videos
        if not is_supported_trailer_url(video.url) and (video.external_url or video.page_url)
    )
    parts = []
    if direct_count:
        noun = "direct video" if direct_count == 1 else "direct videos"
        parts.append(f"{direct_count} {noun}")
    if embedded_count:
        noun = "embedded video" if embedded_count == 1 else "embedded videos"
        if ytdlp_command():
            parts.append(f"{embedded_count} {noun} ready for MP4 download")
        else:
            parts.append(f"{embedded_count} {noun}; yt-dlp needed for MP4 download")
    if not parts:
        noun = "video" if len(videos) == 1 else "videos"
        parts.append(f"{len(videos)} {noun}")
    return "found (" + ", ".join(parts) + ")"


def wrap_row(label: str, value: str) -> list[str]:
    prefix = f"{label}: "
    wrapped = textwrap.wrap(
        value,
        width=100,
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped or [prefix.rstrip()]


def join_list(values: list[str]) -> str:
    return ", ".join(values)


def format_cast(actors: list[Actor]) -> str:
    parts = []
    for actor in actors:
        parts.append(f"{actor.name} as {actor.role}" if actor.role else actor.name)
    return ", ".join(parts)


def scrape_url(url: str) -> Metadata:
    normalized = normalize_url(url)
    provider = provider_for_url(normalized)
    if not provider:
        raise UnsupportedProviderError(UNSUPPORTED_PROVIDER_MESSAGE)
    if provider == "metopera":
        return metadata_from_metopera(normalized, detail_link=url)
    if provider == "broadwayhd":
        return metadata_from_broadwayhd(normalized, detail_link=url)

    html_text, final_url, warnings = fetch_html(normalized)
    meta = parse_detail_page(html_text, final_url, detail_link=url)
    meta.warnings.extend(warnings)
    return meta


def provider_for_url(url: str) -> str:
    for provider_key, _provider_name, matcher in PROVIDER_HANDLERS:
        if matcher(url):
            return provider_key
    return ""


def print_parsed_links(links: list[str]) -> None:
    print("\nParsed link(s):")
    for index, link in enumerate(links, start=1):
        print(f"{index}. {link}")


def get_links_from_user() -> list[str]:
    links: list[str] = []
    while True:
        link = get_link_from_user()
        links.append(link)
        if not ask_required_yes_no("Would you like to paste another link?"):
            print_parsed_links(links)
            return links


def get_link_from_user() -> str:
    while True:
        link = input("Paste your detail page link: ").strip()
        if not link:
            print("Please paste a link before continuing.")
            continue
        return link


def choose_link_input_mode() -> str:
    print("\nWould you like to import your mylinks.txt or manually insert links here?")
    print("1. Import your mylinks.txt")
    print("2. Manually insert links here")
    while True:
        answer = input("Choose 1 or 2: ").strip()
        if answer in {"1", "2"}:
            return answer
        print("Please type 1 or 2.")


def mylinks_path() -> Path:
    return project_root() / MY_LINKS_DIR_NAME / MY_LINKS_FILE_NAME


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_mylinks_entries() -> list[LinkEntry]:
    path = mylinks_path()
    if not path.exists():
        raise ValueError(f"Could not find {path}.")

    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[LinkEntry] = []
    index = 0
    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break

        first_line = lines[index].strip()
        index += 1
        if is_http_url(first_line):
            entries.append(LinkEntry(title="", url=first_line))
        else:
            title_line = first_line.rstrip(":").strip()
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index >= len(lines):
                raise ValueError(f"{MY_LINKS_FILE_NAME} is missing a link after {first_line}")
            link_line = lines[index].strip()
            index += 1
            if not is_http_url(link_line):
                raise ValueError(f"{MY_LINKS_FILE_NAME} has an invalid link after {first_line}")
            entries.append(LinkEntry(title=title_line, url=link_line))

        while index < len(lines) and not lines[index].strip():
            index += 1

    return entries


def is_http_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def comparable_url(value: str) -> str:
    return clean_text(value).rstrip("/")


def existing_output_links(output_dir: Path) -> set[str]:
    links: set[str] = set()
    for nfo_path in output_dir.glob("*/*.nfo"):
        try:
            root = ET.parse(nfo_path).getroot()
        except (ET.ParseError, OSError):
            continue
        for tag in ("detail_link", "source_url"):
            value = root.findtext(tag, default="")
            if value:
                links.add(comparable_url(value))
    return links


def is_existing_output_link(url: str, existing_links: set[str]) -> bool:
    return comparable_url(url) in existing_links


def expected_nfo_path_for_metadata(output_dir: Path, meta: Metadata) -> Path:
    filename_base = metadata_bundle_name(meta)
    return output_folder_for_metadata(output_dir, meta) / f"{safe_filename(filename_base)}.nfo"


def ask_required_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt + " [Y/N]: ").strip().casefold()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer Y or N.")


def summarize_save_results(save_results: list[SaveResult], output_dir: Path) -> str:
    folder_count = len({result.folder for result in save_results})
    item_count = sum(len(result.items) for result in save_results)
    return (
        f"\nDone. Saved {folder_count} folder(s) with "
        f"{item_count} item(s) total in {output_dir}."
    )


def print_saved_result(result: SaveResult) -> None:
    print(f"Saved folder: {result.folder}")


def scrape_links(links: list[str]) -> list[Metadata]:
    results: list[Metadata] = []
    for link in links:
        try:
            print(f"\nChecking {link} ...")
            results.append(scrape_url(link))
        except UnsupportedProviderError:
            print(UNSUPPORTED_PROVIDER_MESSAGE)
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as error:
            print(f"Could not scrape {link}: {error}")
    return results


def save_selected_results(results: list[Metadata], output_dir: Path) -> list[SaveResult]:
    save_results: list[SaveResult] = []
    for result in results:
        title = result.title or "this title"
        if ask_yes_no(f"Save folder for {title}?", default=True):
            save_result = save_title_folder(result, output_dir)
            if save_result:
                save_results.append(save_result)
                print_saved_result(save_result)
        else:
            print(f"Skipped: {title}")
    return save_results


def review_all_at_once(links: list[str], output_dir: Path) -> int:
    results = scrape_links(links)
    if not results:
        print("No metadata could be scraped.")
        return 1

    print("\nAll scraped results are shown below. No .nfo files have been saved yet.")
    for index, result in enumerate(results, start=1):
        print(f"\nPreview {index} of {len(results)}")
        print(format_preview(result))

    print("\nAll previews are complete. Now choose what to save.")
    save_results = save_selected_results(results, output_dir)
    print(summarize_save_results(save_results, output_dir))
    return 0 if save_results else 1


def review_one_at_a_time(links: list[str], output_dir: Path) -> int:
    save_results: list[SaveResult] = []
    print("\nOne-at-a-time review selected. Each result will be previewed before it can be saved.")
    for link in links:
        try:
            print(f"\nChecking {link} ...")
            result = scrape_url(link)
        except UnsupportedProviderError:
            print(UNSUPPORTED_PROVIDER_MESSAGE)
            continue
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as error:
            print(f"Could not scrape {link}: {error}")
            continue

        print(format_preview(result))
        if ask_yes_no("Save this title folder?", default=True):
            save_result = save_title_folder(result, output_dir)
            if save_result:
                save_results.append(save_result)
                print_saved_result(save_result)
        else:
            title = result.title or "this title"
            print(f"Skipped: {title}")

    print(summarize_save_results(save_results, output_dir))
    return 0 if save_results else 1


def review_mylinks_file(output_dir: Path) -> int:
    try:
        entries = load_mylinks_entries()
    except ValueError as error:
        print(f"Could not import {MY_LINKS_FILE_NAME}: {error}")
        return 1

    if not entries:
        print(f"No links were found in {mylinks_path()}.")
        return 1

    save_results: list[SaveResult] = []
    existing_links = existing_output_links(output_dir)

    for entry in entries:
        if is_existing_output_link(entry.url, existing_links):
            print(f"\nSkipped existing link: {entry.url}")
            continue

        try:
            print(f"\nChecking {entry.url} ...")
            result = scrape_url(entry.url)
        except UnsupportedProviderError:
            print(UNSUPPORTED_PROVIDER_MESSAGE)
            continue
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as error:
            print(f"Could not scrape {entry.url}: {error}")
            continue

        expected_nfo_path = expected_nfo_path_for_metadata(output_dir, result)
        if expected_nfo_path.exists():
            print(f"Skipped existing folder: {expected_nfo_path.parent.name}")
            continue

        save_result = save_title_folder(result, output_dir)
        if save_result:
            save_results.append(save_result)
            print_saved_result(save_result)
            existing_links.add(comparable_url(entry.url))
            if result.source_url:
                existing_links.add(comparable_url(result.source_url))

    print(summarize_save_results(save_results, output_dir))
    return 0 if save_results else 1


def review_links_until_done(output_dir: Path) -> int:
    save_results: list[SaveResult] = []
    print(f"\nOutput folder: {output_dir}")

    if choose_link_input_mode() == "1":
        return review_mylinks_file(output_dir)

    while True:
        link = get_link_from_user()
        try:
            print(f"\nChecking {link} ...")
            result = scrape_url(link)
        except UnsupportedProviderError:
            print(UNSUPPORTED_PROVIDER_MESSAGE)
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as error:
            print(f"Could not scrape {link}: {error}")
        else:
            print(format_preview(result))
            if ask_yes_no("Save this title folder?", default=True):
                save_result = save_title_folder(result, output_dir)
                if save_result:
                    save_results.append(save_result)
                    print_saved_result(save_result)
            else:
                title = result.title or "this title"
                print(f"Skipped: {title}")

        if not ask_required_yes_no("Would you like to paste another link?"):
            break

    print(summarize_save_results(save_results, output_dir))
    return 0 if save_results else 1


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = input(prompt + suffix).strip().casefold()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.")


def choose_review_mode(link_count: int) -> str:
    if link_count <= 1:
        print("\nReview mode: one link provided, so it will be previewed before saving.")
        return "one"

    print("\nHow do you want to review the results before anything is saved?")
    print("1. One at a time: scrape one link, preview it, then choose whether to save it.")
    print("2. All at once: scrape every link first, show every preview, then choose what to save.")
    while True:
        answer = input("Choose 1 or 2 [1]: ").strip()
        if not answer or answer == "1":
            return "one"
        if answer == "2":
            return "all"
        print("Please type 1 or 2.")


def main() -> int:
    output_dir = project_root() / "Output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(WELCOME_MESSAGE, end="")
    return review_links_until_done(output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
