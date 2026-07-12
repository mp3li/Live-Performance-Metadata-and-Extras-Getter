#!/usr/bin/env python3
"""
Met Opera On Demand metadata helpers.

The live radio page is a JavaScript app. Its public page data comes from the
Met Opera On Demand middleware API, so this provider reads that structured JSON
instead of trying to guess from the app shell HTML.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


API_BASE = "https://middleware.ondemand.metopera.org/client"
PAGE_HOSTS = {"ondemand.metopera.org"}
NAME = "Metropolitan Opera Livestream"
STUDIO_NAME = "The Metropolitan Opera"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


@dataclass
class MetOperaCastMember:
    name: str = ""
    role: str = ""
    credit_type: str = ""


@dataclass
class MetOperaTrack:
    title: str = ""
    artists: str = ""
    featured: str = ""
    is_free: str = ""
    isrc: str = ""
    time_seconds: int = 0


@dataclass
class MetOperaMetadata:
    source_url: str = ""
    detail_link: str = ""
    item_id: str = ""
    broadcast_id: str = ""
    title: str = ""
    media_type: str = ""
    class_type: str = ""
    performance_date: str = ""
    runtime_minutes: str = ""
    plot: str = ""
    full_synopsis: str = ""
    world_premiere: str = ""
    brief_synopsis: str = ""
    full_synopsis_url: str = ""
    start: str = ""
    end: str = ""
    tier: str = ""
    met_id: str = ""
    ext_id: str = ""
    short_cast: str = ""
    poster_url: str = ""
    wide_url: str = ""
    subtitle_url: str = ""
    cast: list[MetOperaCastMember] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    composers: list[str] = field(default_factory=list)
    conductors: list[str] = field(default_factory=list)
    librettists: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    tracks: list[MetOperaTrack] = field(default_factory=list)
    current_track: MetOperaTrack | None = None


def is_metopera_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    host = parsed.netloc.casefold()
    return host in PAGE_HOSTS or host.endswith(".metopera.org")


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    if not is_metopera_url(url):
        return False
    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) >= 2 and parts[0] in {"broadcast", "performance"}


def extract_metadata(url: str, timeout: int = 25) -> MetOperaMetadata:
    parsed = urllib.parse.urlparse(clean_text(url))
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Met Opera links need a broadcast or performance ID.")

    kind = parts[0]
    item_id = parts[1]
    if kind == "broadcast":
        broadcast = fetch_json(f"{API_BASE}/broadcast/{item_id}", timeout=timeout)
        item = choose_active_schedule_item(broadcast) or first_schedule_item(broadcast)
        if not item:
            raise ValueError("No scheduled Met Opera item was found in this broadcast.")
        performance = fetch_json(f"{API_BASE}/performance/{item.get('id')}", timeout=timeout)
        metadata = build_metadata(
            performance,
            detail_link=url,
            source_url=url,
            broadcast_id=item_id,
            schedule_item=item,
        )
        apply_full_synopsis(metadata, timeout=timeout)
        return metadata

    if kind == "performance":
        performance = fetch_json(f"{API_BASE}/performance/{item_id}", timeout=timeout)
        metadata = build_metadata(performance, detail_link=url, source_url=url)
        apply_full_synopsis(metadata, timeout=timeout)
        return metadata

    raise ValueError("Unsupported Met Opera link.")


def fetch_json(url: str, timeout: int = 25) -> dict[str, Any]:
    data = json.loads(fetch_text(url, timeout=timeout))
    if not isinstance(data, dict):
        raise ValueError("Met Opera API returned an unexpected response.")
    return data


def fetch_text(url: str, timeout: int = 25, max_bytes: int = 80 * 1024 * 1024) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except (urllib.error.URLError, TimeoutError):
        data = fetch_bytes_with_curl(url, timeout=timeout, max_bytes=max_bytes)
    if len(data) > max_bytes:
        raise RuntimeError(f"download exceeded {max_bytes} bytes")
    return data.decode("utf-8", errors="replace")


def fetch_bytes_with_curl(url: str, timeout: int, max_bytes: int) -> bytes:
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
    result = subprocess.run(command, capture_output=True, check=False, timeout=timeout + 10)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"curl exited with {result.returncode}")
    return result.stdout


def choose_active_schedule_item(data: dict[str, Any]) -> dict[str, Any] | None:
    items = schedule_items(data)
    now = datetime.now(timezone.utc)
    for item in items:
        start = parse_utc_datetime(item.get("start"))
        end = parse_utc_datetime(item.get("end"))
        if start and end and start <= now < end:
            return item
    return None


def first_schedule_item(data: dict[str, Any]) -> dict[str, Any] | None:
    items = schedule_items(data)
    return items[0] if items else None


def schedule_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    for component in data.get("components", []):
        if isinstance(component, dict) and component.get("type") == "SCHEDULE":
            items = component.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def build_metadata(
    performance: dict[str, Any],
    detail_link: str,
    source_url: str,
    broadcast_id: str = "",
    schedule_item: dict[str, Any] | None = None,
) -> MetOperaMetadata:
    schedule_item = schedule_item or {}
    title = clean_text(
        performance.get("title")
        or performance.get("name")
        or schedule_item.get("title")
        or nested_text(performance, ("tile", "header"))
    )
    tracks = parse_tracks(performance.get("cuePoints") or [])
    current_track = current_track_for_schedule(schedule_item, tracks)
    poster_url, wide_url = choose_images(performance)
    ext_id = clean_text(performance.get("extId") or schedule_item.get("extId"))

    metadata = MetOperaMetadata(
        source_url=source_url,
        detail_link=detail_link,
        item_id=clean_text(performance.get("id") or schedule_item.get("id")),
        broadcast_id=broadcast_id,
        title=title,
        media_type=clean_text(performance.get("mediaType") or schedule_item.get("mediaType")),
        class_type=clean_text(performance.get("classType")),
        performance_date=clean_text(
            performance.get("performanceDate") or schedule_item.get("performanceDate")
        ),
        runtime_minutes=runtime_minutes(performance.get("runTime") or performance.get("liveDuration")),
        plot=clean_html_text(performance.get("fullSynopsis") or schedule_item.get("fullSynopsis")),
        brief_synopsis=clean_html_text(
            performance.get("briefSynopsis") or schedule_item.get("briefSynopsis")
        ),
        full_synopsis_url=clean_text(performance.get("fullSynopsisUrl")),
        start=clean_text(schedule_item.get("start") or performance.get("start")),
        end=clean_text(schedule_item.get("end") or performance.get("end")),
        tier=clean_text(performance.get("tier") or schedule_item.get("tier")),
        met_id=clean_text(performance.get("metID") or schedule_item.get("metID")),
        ext_id=ext_id,
        short_cast=clean_html_text(performance.get("shortCast") or schedule_item.get("shortCast")),
        poster_url=poster_url,
        wide_url=wide_url,
        subtitle_url=subtitle_url(ext_id),
        cast=parse_cast(performance.get("cast") or schedule_item.get("cast") or []),
        genres=[clean_text(value) for value in performance.get("genres") or [] if clean_text(value)],
        tags=[clean_text(value) for value in performance.get("tags") or [] if clean_text(value)],
        tracks=tracks,
        current_track=current_track,
    )
    classify_cast(metadata)
    return metadata


def apply_full_synopsis(metadata: MetOperaMetadata, timeout: int = 25) -> None:
    if not metadata.full_synopsis_url:
        return
    try:
        synopsis = fetch_synopsis(metadata.full_synopsis_url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return
    if synopsis.get("world_premiere"):
        metadata.world_premiere = synopsis["world_premiere"]
    if synopsis.get("full_synopsis"):
        metadata.full_synopsis = synopsis["full_synopsis"]


def fetch_synopsis(url: str, timeout: int = 25) -> dict[str, str]:
    html_text = fetch_text(url, timeout=timeout)

    match = re.search(
        r'id=["\']hdnSynopsisText["\'][^>]*\bvalue=(["\'])(.*?)\1',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    raw_value = html.unescape(match.group(2))
    entries = json.loads(raw_value)
    if not isinstance(entries, list):
        return {}
    entry = next(
        (
            item
            for item in entries
            if isinstance(item, dict)
            and clean_text(item.get("language")).casefold() == "english"
        ),
        entries[0] if entries and isinstance(entries[0], dict) else {},
    )
    if not isinstance(entry, dict):
        return {}

    pieces: list[str] = []
    acts = entry.get("acts")
    if isinstance(acts, list):
        for act in acts:
            if not isinstance(act, dict):
                continue
            act_key = clean_text(act.get("actKey"))
            act_value = html_fragment_to_text(clean_text(act.get("actValue")))
            if act_key and act_value:
                pieces.append(f"{act_key}\n\n{act_value}")
    return {
        "world_premiere": clean_text(entry.get("intro")),
        "full_synopsis": "\n\n".join(pieces),
    }


def html_fragment_to_text(value: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</\s*p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_cast(cast_rows: Any) -> list[MetOperaCastMember]:
    output: list[MetOperaCastMember] = []
    if not isinstance(cast_rows, list):
        return output
    seen: set[tuple[str, str, str]] = set()
    for row in cast_rows:
        if not isinstance(row, dict):
            continue
        person = row.get("person") if isinstance(row.get("person"), dict) else {}
        name = clean_text(person.get("name"))
        credit_type = clean_text(row.get("role")).upper()
        role = clean_text(row.get("roleName"))
        key = (name.casefold(), role.casefold(), credit_type.casefold())
        if name and key not in seen:
            output.append(MetOperaCastMember(name=name, role=role, credit_type=credit_type))
            seen.add(key)
    return output


def classify_cast(metadata: MetOperaMetadata) -> None:
    for member in metadata.cast:
        if member.credit_type == "COMPOSER":
            add_unique(metadata.composers, member.name)
        elif member.credit_type == "CONDUCTOR":
            add_unique(metadata.conductors, member.name)
        elif member.credit_type == "LIBRETTIST":
            add_unique(metadata.librettists, member.name)
        elif member.credit_type == "GROUP":
            add_unique(metadata.groups, member.name)


def parse_tracks(cue_points: Any) -> list[MetOperaTrack]:
    tracks: list[MetOperaTrack] = []
    if not isinstance(cue_points, list):
        return tracks
    for cue in cue_points:
        if not isinstance(cue, dict):
            continue
        metadata = parse_cue_metadata(cue.get("metadata"))
        title = clean_text(metadata.get("title") or cue.get("name"))
        if not title:
            continue
        tracks.append(
            MetOperaTrack(
                title=title,
                artists=clean_text(metadata.get("artists")),
                featured=clean_text(metadata.get("featured")),
                is_free=clean_text(metadata.get("isFree")),
                isrc=clean_text(metadata.get("ISRC") or metadata.get("isrc")),
                time_seconds=int(float(cue.get("time") or 0)),
            )
        )
    return sorted(tracks, key=lambda track: track.time_seconds)


def parse_cue_metadata(value: Any) -> dict[str, str]:
    text = clean_text(value)
    output: dict[str, str] = {}
    if not text:
        return output
    for part in text.split("|"):
        key, separator, item_value = part.partition("=")
        if separator:
            output[clean_text(key)] = clean_text(item_value)
    return output


def current_track_for_schedule(
    schedule_item: dict[str, Any], tracks: list[MetOperaTrack]
) -> MetOperaTrack | None:
    if not schedule_item or not tracks:
        return None
    start = parse_utc_datetime(schedule_item.get("start"))
    end = parse_utc_datetime(schedule_item.get("end"))
    now = datetime.now(timezone.utc)
    if not start or not end or not (start <= now < end):
        return None
    offset_seconds = int((now - start).total_seconds())
    current = tracks[0]
    for track in tracks:
        if track.time_seconds <= offset_seconds:
            current = track
        else:
            break
    return current


def choose_images(data: dict[str, Any]) -> tuple[str, str]:
    poster = ""
    wide = ""
    for container_name in ("mobileTile", "tile", "slide"):
        candidate = nested_text(data, (container_name, "image", "url"))
        if candidate and not poster:
            poster = candidate
        if candidate and not wide:
            wide = candidate
    for candidate in find_image_urls(data):
        lowered = candidate.casefold()
        if not poster and ("300x300" in lowered or "audio_300x300" in lowered):
            poster = candidate
        if not wide and ("1280x720" in lowered or "image.jpg" in lowered):
            wide = candidate
        if not poster:
            poster = candidate
        if not wide:
            wide = candidate
    return poster, wide or poster


def find_image_urls(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            found.extend(find_image_urls(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(find_image_urls(item))
    elif isinstance(value, str):
        text = clean_text(value)
        if re.search(r"\.(?:jpg|jpeg|png|webp)(?:$|\?)", text, flags=re.IGNORECASE):
            found.append(text)
    return dedupe(found)


def subtitle_url(ext_id: str) -> str:
    ext_id = clean_text(ext_id)
    if not ext_id:
        return ""
    return f"https://www.metopera.org/ondemand/imagelinks/subtitles/{ext_id}.srt"


def runtime_minutes(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number > 10000:
        number = number / 1000
    minutes = int(round(number / 60))
    return str(minutes) if minutes > 0 else ""


def parse_utc_datetime(value: Any) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def nested_text(data: dict[str, Any], path: tuple[str, ...]) -> str:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return clean_text(current)


def add_unique(values: list[str], value: str) -> None:
    folded = value.casefold()
    if value and folded not in {item.casefold() for item in values}:
        values.append(value)


def dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = clean_text(value)
        folded = cleaned.casefold()
        if cleaned and folded not in seen:
            output.append(cleaned)
            seen.add(folded)
    return output


def clean_text(value: Any) -> str:
    text = html.unescape("" if value is None else str(value))
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_html_text(value: Any) -> str:
    text = clean_text(re.sub(r"<br\s*/?>", "\n", "" if value is None else str(value), flags=re.I))
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(text)
