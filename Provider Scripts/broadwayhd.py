#!/usr/bin/env python3
"""
BroadwayHD detail-page extraction helpers.

BroadwayHD pages are rendered by a JavaScript app. The public detail data comes
from the same front-office JSON endpoints the page calls, so this provider reads
those structured responses instead of scraping the empty app shell.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


NAME = "BroadwayHD"
STUDIO_NAME = "BroadwayHD"
API_BASE = "https://dce-frontoffice.imggaming.com"
API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
DEFAULT_REALM = "dce.bhd"
PAGE_HOSTS = {"broadwayhd.com", "www.broadwayhd.com"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
INIT_QUERY = (
    "lk=language&pk=subTitleLanguage&pk=subtitlePreferenceMode&"
    "pk=subtitlePreferenceMap&pk=audioLanguage&pk=autoAdvance&"
    "pk=pluginAccessTokens&pk=videoBackgroundAutoPlay&readLicences=true&"
    "countEvents=LIVE&menuTargetPlatform=MOBILE-WEB&readIconStore=ENABLED&"
    "readUserProfiles=true&altMenuTargetPlatform=WEB"
)
SECTION_QUERY = (
    "bpp=10&rpp=12&displaySectionLinkBuckets=SHOW&displayEpgBuckets=HIDE&"
    "displayEmptyBucketShortcuts=SHOW&displayContentAvailableOnSignIn=SHOW&"
    "displayGeoblocked=HIDE&bspp=20&premiereEventContentDisplay=SHOW&"
    "displayHeroLicences=SHOW"
)


@dataclass
class BroadwayHDCredit:
    name: str = ""
    role: str = ""


@dataclass
class BroadwayHDMetadata:
    source_url: str = ""
    detail_link: str = ""
    item_id: str = ""
    title: str = ""
    plot: str = ""
    year: str = ""
    runtime_minutes: str = ""
    poster_url: str = ""
    wide_url: str = ""
    logo_url: str = ""
    trailer_url: str = ""
    trailer_id: str = ""
    external_asset_id: str = ""
    genres: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    film_directors: list[str] = field(default_factory=list)
    writers: list[str] = field(default_factory=list)
    music_and_lyrics: list[str] = field(default_factory=list)
    producers: list[str] = field(default_factory=list)
    executive_producers: list[str] = field(default_factory=list)
    credits: list[BroadwayHDCredit] = field(default_factory=list)


def is_broadwayhd_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    host = parsed.netloc.casefold()
    return host in PAGE_HOSTS


def is_supported_url(url: str) -> bool:
    return bool(is_broadwayhd_url(url) and (video_id_from_url(url) or section_id_from_url(url)))


def extract_metadata(url: str, timeout: int = 25) -> BroadwayHDMetadata:
    item_id = video_id_from_url(url)
    if not item_id:
        raise ValueError("BroadwayHD links need a /video/ ID.")

    session = fetch_session(timeout=timeout)
    view = fetch_json(
        f"{API_BASE}/api/v1/view?type=vod&id={item_id}&timezone=America%2FLos_Angeles",
        headers=session.auth_headers,
        timeout=timeout,
    )
    vod = fetch_json(
        f"{API_BASE}/api/v4/vod/{item_id}?includePlaybackDetails=URL",
        headers=session.auth_headers,
        timeout=timeout,
    )

    metadata = BroadwayHDMetadata(
        source_url=f"https://broadwayhd.com/video/{item_id}",
        detail_link=url,
        item_id=item_id,
    )
    apply_vod_data(metadata, vod)
    apply_view_data(metadata, view)
    if not metadata.title:
        metadata.title = f"BroadwayHD video {item_id}"
    return metadata


def section_video_urls(url: str, timeout: int = 25) -> list[str]:
    section_id = section_id_from_url(url)
    if not section_id:
        return []

    session = fetch_session(timeout=timeout)
    data = fetch_json(
        f"{API_BASE}/api/v4/content/{section_id}?{SECTION_QUERY}",
        headers=session.auth_headers,
        timeout=timeout,
    )
    ids = section_video_ids(data)
    return [f"https://broadwayhd.com/video/{item_id}" for item_id in ids]


@dataclass
class BroadwayHDSession:
    realm: str
    token: str

    @property
    def auth_headers(self) -> dict[str, str]:
        headers = default_headers()
        headers["Realm"] = self.realm
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers


def fetch_session(timeout: int) -> BroadwayHDSession:
    init = fetch_json(
        f"{API_BASE}/api/v1/init/?{INIT_QUERY}",
        headers=default_headers(),
        timeout=timeout,
    )
    realm = clean_text(nested_value(init, ("settings", "realm"))) or DEFAULT_REALM
    token = clean_text(nested_value(init, ("authentication", "authorisationToken")))
    return BroadwayHDSession(realm=realm, token=token)


def default_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://broadwayhd.com",
        "Referer": "https://broadwayhd.com/",
        "x-api-key": API_KEY,
        "x-app": "dice-web",
    }


def fetch_json(url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    text = fetch_text(url, headers=headers, timeout=timeout)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("BroadwayHD API returned an unexpected response.")
    return data


def fetch_text(url: str, headers: dict[str, str], timeout: int) -> str:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return fetch_text_with_curl(url, headers=headers, timeout=timeout)


def fetch_text_with_curl(url: str, headers: dict[str, str], timeout: int) -> str:
    command = [
        "/usr/bin/curl",
        "--location",
        "--fail",
        "--silent",
        "--show-error",
        "--compressed",
        "--max-time",
        str(timeout),
    ]
    for name, value in headers.items():
        if name.casefold() == "user-agent":
            command.extend(["--user-agent", value])
        else:
            command.extend(["--header", f"{name}: {value}"])
    command.append(url)
    result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exited with {result.returncode}")
    return result.stdout


def apply_vod_data(metadata: BroadwayHDMetadata, vod: dict[str, Any]) -> None:
    metadata.title = clean_text(vod.get("title")) or metadata.title
    metadata.plot = clean_text(vod.get("description")) or metadata.plot
    metadata.poster_url = clean_text(vod.get("posterUrl")) or metadata.poster_url
    metadata.wide_url = clean_text(vod.get("coverUrl")) or metadata.wide_url
    metadata.external_asset_id = clean_text(vod.get("externalAssetId"))

    for tag in vod.get("typedTags") or []:
        if not isinstance(tag, dict):
            continue
        name = clean_text(tag.get("name")).casefold()
        value = clean_text(tag.get("value"))
        if not value:
            continue
        if name == "genre":
            add_unique(metadata.genres, value)
        elif name == "year":
            metadata.year = value

    if not metadata.runtime_minutes:
        metadata.runtime_minutes = runtime_minutes(vod.get("duration"))
    if not metadata.poster_url:
        metadata.poster_url = clean_text(vod.get("thumbnailUrl"))
    if not metadata.wide_url:
        metadata.wide_url = clean_text(vod.get("thumbnailUrl"))


def apply_view_data(metadata: BroadwayHDMetadata, view: dict[str, Any]) -> None:
    hero = first_element_of_type(view, "hero") or {}
    attributes = hero.get("attributes") if isinstance(hero.get("attributes"), dict) else {}

    title = text_from_header(attributes.get("header")) or breakpoint_header_text(attributes)
    if title and not looks_like_image_url(title):
        metadata.title = title

    logo = image_source(attributes.get("header"))
    if logo:
        metadata.logo_url = logo

    wide = image_source(attributes.get("image"))
    if wide:
        metadata.wide_url = wide

    tags = hero_tags(attributes)
    if tags:
        runtime = runtime_from_tag_list(tags)
        if runtime:
            metadata.runtime_minutes = runtime
        for tag in tags:
            if re.fullmatch(r"(18\d{2}|19\d{2}|20\d{2}|21\d{2})", tag):
                metadata.year = tag
            elif tag and not re.search(r"\d", tag) and tag.casefold() not in {"new"}:
                add_unique(metadata.genres, tag)

    plot = first_hero_description(attributes)
    if plot:
        metadata.plot = plot

    trailer = first_trailer(attributes)
    if trailer:
        trailer_id = clean_text(trailer.get("id"))
        metadata.trailer_id = trailer_id
        if trailer_id:
            metadata.trailer_url = (
                f"https://broadwayhd.com/video/{trailer_id}?trailerFrom={metadata.item_id}"
            )

    for credit in people_credits(view):
        metadata.credits.append(credit)
        role = credit.role.casefold()
        if role == "cast":
            add_unique(metadata.cast, credit.name)
        elif role == "director":
            add_unique(metadata.directors, credit.name)
        elif role == "film director":
            add_unique(metadata.film_directors, credit.name)
        elif role == "book":
            add_unique(metadata.writers, credit.name)
        elif role == "music & lyrics":
            add_unique(metadata.music_and_lyrics, credit.name)
        elif role == "producer":
            add_unique(metadata.producers, credit.name)
        elif role == "executive producer":
            add_unique(metadata.executive_producers, credit.name)


def video_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(clean_text(url))
    match = re.search(r"/video/(\d+)", parsed.path)
    return match.group(1) if match else ""


def section_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(clean_text(url))
    match = re.search(r"/section/([^/?#]+)", parsed.path)
    if not match:
        return ""
    return urllib.parse.quote(urllib.parse.unquote(match.group(1)), safe="")


def is_section_url(url: str) -> bool:
    return bool(is_broadwayhd_url(url) and section_id_from_url(url))


def section_video_ids(data: dict[str, Any]) -> list[str]:
    ids: list[str] = []

    for bucket in data.get("buckets") or []:
        if not isinstance(bucket, dict):
            continue
        for item in bucket.get("contentList") or []:
            add_vod_id(ids, item)

    for hero in data.get("heroes") or []:
        for item in vod_items(hero):
            add_vod_id(ids, item)

    return ids


def vod_items(value: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("type") == "VOD" and value.get("id"):
            output.append(value)
        for item in value.values():
            output.extend(vod_items(item))
    elif isinstance(value, list):
        for item in value:
            output.extend(vod_items(item))
    return output


def add_vod_id(ids: list[str], item: Any) -> None:
    if not isinstance(item, dict) or item.get("type") != "VOD":
        return
    item_id = clean_text(item.get("id"))
    if item_id and item_id not in ids:
        ids.append(item_id)


def first_element_of_type(data: Any, type_name: str) -> dict[str, Any] | None:
    if isinstance(data, dict):
        if clean_text(data.get("$type")).casefold() == type_name.casefold():
            return data
        for value in data.values():
            match = first_element_of_type(value, type_name)
            if match:
                return match
    elif isinstance(data, list):
        for item in data:
            match = first_element_of_type(item, type_name)
            if match:
                return match
    return None


def people_credits(data: Any) -> list[BroadwayHDCredit]:
    credits: list[BroadwayHDCredit] = []
    seen: set[tuple[str, str]] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if clean_text(value.get("$type")).casefold() == "gridblock":
                elements = nested_value(value, ("attributes", "elements"))
                if isinstance(elements, list) and len(elements) == 2:
                    texts = [
                        clean_text(nested_value(element, ("attributes", "text")))
                        for element in elements
                        if isinstance(element, dict)
                        and clean_text(element.get("$type")).casefold() == "textblock"
                    ]
                    if len(texts) == 2 and texts[0] and texts[1]:
                        key = (texts[0].casefold(), texts[1].casefold())
                        if key not in seen:
                            credits.append(BroadwayHDCredit(name=texts[0], role=texts[1]))
                            seen.add(key)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return credits


def hero_tags(attributes: dict[str, Any]) -> list[str]:
    for item in attributes.get("content") or []:
        if not isinstance(item, dict):
            continue
        if clean_text(item.get("$type")).casefold() != "taglist":
            continue
        tags = nested_value(item, ("attributes", "tags"))
        if not isinstance(tags, list):
            continue
        return [
            clean_text(nested_value(tag, ("attributes", "text")))
            for tag in tags
            if clean_text(nested_value(tag, ("attributes", "text")))
        ]
    return []


def runtime_from_tag_list(tags: list[str]) -> str:
    for tag in tags:
        runtime = runtime_minutes(tag)
        if runtime:
            return runtime
    return ""


def first_hero_description(attributes: dict[str, Any]) -> str:
    for item in attributes.get("content") or []:
        if not isinstance(item, dict):
            continue
        if clean_text(item.get("$type")).casefold() == "textblock":
            text = clean_text(nested_value(item, ("attributes", "text")))
            if text and len(text) > 5:
                return text
    return ""


def first_trailer(attributes: dict[str, Any]) -> dict[str, Any]:
    for item in attributes.get("content") or []:
        buttons = nested_value(item, ("attributes", "buttons"))
        if not isinstance(buttons, list):
            continue
        for button in buttons:
            action = nested_value(button, ("attributes", "action"))
            if not isinstance(action, dict) or action.get("type") != "trailer":
                continue
            trailers = nested_value(action, ("data", "trailers"))
            if isinstance(trailers, list) and trailers and isinstance(trailers[0], dict):
                return trailers[0]
    return {}


def image_source(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if clean_text(value.get("$type")).casefold() != "image":
        return ""
    return clean_text(nested_value(value, ("attributes", "source")))


def text_from_header(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if clean_text(value.get("$type")).casefold() != "header":
        return ""
    return clean_text(nested_value(value, ("attributes", "text")))


def breakpoint_header_text(attributes: dict[str, Any]) -> str:
    breakpoints = attributes.get("breakpoints")
    if not isinstance(breakpoints, dict):
        return ""
    for breakpoint in ("mobile", "tablet", "desktop"):
        text = text_from_header(nested_value(breakpoints, (breakpoint, "header")))
        if text:
            return text
    return ""


def nested_value(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def runtime_minutes(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        total = int(value) // 60
        return str(total) if total else ""
    text = clean_text(value)
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
    return ""


def looks_like_image_url(url: str) -> bool:
    path = urllib.parse.urlparse(clean_text(url)).path.casefold()
    return bool(re.search(r"\.(?:jpg|jpeg|png|webp)(?:$|[._-])", path))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def add_unique(values: list[str], value: Any) -> None:
    text = clean_text(value)
    if text and text.casefold() not in {item.casefold() for item in values}:
        values.append(text)
