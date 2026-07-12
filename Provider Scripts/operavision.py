#!/usr/bin/env python3
"""
OperaVision detail-page extraction helpers.

OperaVision pages are server-rendered enough for the standard HTML fetcher, but
their visible text is arranged in site-specific sections. This module keeps that
page knowledge out of the generic NFO writer.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field


NAME = "OperaVision"

SECTION_HEADINGS = {
    "cast",
    "gallery",
    "insights",
    "story",
    "the story",
    "video",
    "videos",
}

VIDEO_KINDS = {
    "behind the scenes",
    "extract",
    "flashback",
    "introduction",
    "teaser",
    "trailer",
}

CREW_LABELS = {
    "adaptation",
    "choreography",
    "chorus master",
    "conductor",
    "costume design",
    "costumes",
    "director",
    "dramaturgy",
    "illusions",
    "illusion associate",
    "libretto",
    "lighting",
    "lighting design",
    "music",
    "musical adaptations",
    "orchestration",
    "projection design",
    "set design",
    "sets and costumes design",
    "stage director",
}

ROLE_LABEL_HINTS = {
    "ballet",
    "candy floss",
    "chorus",
    "clara",
    "dancers",
    "dancing mistress / rat queen",
    "drosselmeyer",
    "fondant rose couple",
    "fritz",
    "jelly",
    "lead candy cane",
    "orchestra",
    "popcorn",
    "prince",
    "the nutcracker / the prince",
}

NOISE_LINES = {
    "load more",
    "more",
    "play full",
    "read less read more",
    "subscribe to newsletter",
    "streaming in",
}


@dataclass
class OperaVisionVideo:
    title: str = ""
    kind: str = ""
    description: str = ""
    url: str = ""
    page_url: str = ""
    external_url: str = ""


@dataclass
class OperaVisionMetadata:
    production: str = ""
    title: str = ""
    composer: str = ""
    tagline: str = ""
    overview: str = ""
    story: str = ""
    plot: str = ""
    streamed_on: str = ""
    available_until: str = ""
    recorded_on: str = ""
    recorded_date: str = ""
    poster_url: str = ""
    wide_url: str = ""
    logo_url: str = ""
    trailer_url: str = ""
    cast: list[tuple[str, list[str]]] = field(default_factory=list)
    crew: dict[str, list[str]] = field(default_factory=dict)
    gallery_urls: list[str] = field(default_factory=list)
    videos: list[OperaVisionVideo] = field(default_factory=list)


def is_operavision_url(url: str) -> bool:
    host = urllib.parse.urlparse(clean_text(url)).netloc.casefold()
    return host == "operavision.eu" or host.endswith(".operavision.eu")


def extract_metadata(
    html_text: str, visible_text: str, source_url: str = "", detail_link: str = ""
) -> OperaVisionMetadata:
    if not (is_operavision_url(source_url) or is_operavision_url(detail_link)):
        return OperaVisionMetadata()

    lines = parse_lines(visible_text)
    metadata = OperaVisionMetadata()

    metadata.title = find_h1_title(html_text) or find_title_from_lines(lines)
    metadata.production = find_production_from_html(html_text) or find_production(
        lines, metadata.title
    )
    metadata.streamed_on, metadata.available_until = find_streaming_window(lines)
    metadata.recorded_on = find_recorded_on(lines)
    metadata.recorded_date = date_to_iso(metadata.recorded_on)

    metadata.tagline, metadata.overview = find_tagline_and_overview(lines, metadata.title)
    metadata.story = find_story(lines)
    metadata.plot = build_plot(metadata.overview, metadata.story)

    metadata.cast, metadata.crew = parse_cast_and_crew(lines)
    metadata.composer = find_composer_from_html(html_text) or find_composer(
        lines, metadata.title
    )
    if metadata.crew.get("Music"):
        metadata.composer = metadata.crew["Music"][0]

    images = find_image_urls(html_text, source_url or detail_link)
    metadata.logo_url = find_logo_url(html_text, images, source_url or detail_link)
    metadata.poster_url = choose_first_image(images, ("header_mobile", "social_media", "header"))
    metadata.wide_url = choose_first_image(images, ("header_mobile", "gallery_grid", "social_media"))
    metadata.gallery_urls = [
        url for url in images if "gallery" in urllib.parse.urlparse(url).path.casefold()
    ]

    direct_video_urls = find_direct_promo_video_urls(html_text, source_url or detail_link)
    video_cards = find_video_cards(html_text, source_url or detail_link)
    metadata.videos = video_cards or find_video_section(lines)
    if direct_video_urls:
        metadata.trailer_url = direct_video_urls[0]
        if not video_cards:
            assign_video_urls(metadata.videos, direct_video_urls)

    return metadata


def parse_lines(visible_text: str) -> list[str]:
    output = []
    for line in visible_text.splitlines():
        cleaned = clean_text(re.sub(r"^#+\s*", "", line))
        if cleaned:
            output.append(cleaned)
    return output


def clean_text(value: object) -> str:
    text = html.unescape("" if value is None else str(value))
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_html_text(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(text)


def clean_production_name(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"\s*/\s*", " ", text)
    return clean_text(text)


def find_h1_title(html_text: str) -> str:
    for match in re.finditer(r"<h1\b[^>]*>(.*?)</h1>", html_text, flags=re.IGNORECASE | re.DOTALL):
        title = clean_html_text(match.group(1))
        if title:
            return title
    return ""


def find_title_from_lines(lines: list[str]) -> str:
    for index, line in enumerate(lines[:-1]):
        if is_date_or_streaming_line(line) or is_noise_line(line):
            continue
        next_line = lines[index + 1]
        if is_date_or_streaming_line(next_line) or is_noise_line(next_line):
            continue
        if is_probable_composer(next_line):
            return line
    return ""


def find_production_from_html(html_text: str) -> str:
    for candidate in find_field_values_by_class(html_text, "field--name-field-reference"):
        production = clean_production_name(candidate)
        if production and not is_noise_line(production):
            return production
    return ""


def find_composer_from_html(html_text: str) -> str:
    for candidate in find_field_values_by_class(html_text, "field--name-field-composer"):
        composer = clean_text(candidate)
        if composer and not is_noise_line(composer):
            return composer
    return ""


def find_field_values_by_class(html_text: str, class_name: str) -> list[str]:
    values: list[str] = []
    pattern = (
        r"<div\b(?=[^>]*\bclass=[\"'][^\"']*"
        + re.escape(class_name)
        + r"\b[^\"']*[\"'])[^>]*>(.*?)</div>"
    )
    for match in re.finditer(pattern, html_text, flags=re.IGNORECASE | re.DOTALL):
        value = clean_html_text(match.group(1))
        if value:
            values.append(value)
    return values


def find_production(lines: list[str], title: str) -> str:
    if not title:
        return ""
    for index, line in enumerate(lines):
        if line != title:
            continue
        for candidate in reversed(lines[max(0, index - 5) : index]):
            if is_noise_line(candidate) or is_credit_line(candidate) or is_image_marker(candidate):
                continue
            if is_date_or_streaming_line(candidate):
                continue
            return clean_production_name(candidate)
    return ""


def find_composer(lines: list[str], title: str) -> str:
    if not title:
        return ""
    for index, line in enumerate(lines[:-1]):
        if line == title:
            candidate = lines[index + 1]
            if not is_noise_line(candidate) and not is_date_or_streaming_line(candidate):
                return candidate
    return ""


def is_probable_composer(line: str) -> bool:
    text = clean_text(line)
    return bool(text and 2 <= len(text) <= 80 and not is_date_or_streaming_line(text))


def find_streaming_window(lines: list[str]) -> tuple[str, str]:
    for index, line in enumerate(lines):
        match = re.search(
            r"(\d{2}\.\d{2}\.\d{4}\s+at\s+\d{1,2}:\d{2}(?:\s+\w+)?)\s+until\s+"
            r"(\d{2}\.\d{2}\.\d{4}\s+at\s+\d{1,2}:\d{2}(?:\s+\w+)?)",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            return clean_text(match.group(1)), clean_text(match.group(2))
        streamed = re.fullmatch(
            r"(\d{2}\.\d{2}\.\d{4}\s+at\s+\d{1,2}:\d{2}(?:\s+\w+)?)",
            clean_text(line),
            flags=re.IGNORECASE,
        )
        if not streamed or index + 1 >= len(lines):
            continue
        available = re.fullmatch(
            r"until\s+(\d{2}\.\d{2}\.\d{4}\s+at\s+\d{1,2}:\d{2}(?:\s+\w+)?)",
            clean_text(lines[index + 1]),
            flags=re.IGNORECASE,
        )
        if available:
            return clean_text(streamed.group(1)), clean_text(available.group(1))
    return "", ""


def find_recorded_on(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if "recorded on" not in line.casefold():
            continue
        same_line = re.search(r"(\d{2}\.\d{2}\.\d{4})", line)
        if same_line:
            return same_line.group(1)
        for candidate in lines[index + 1 : index + 4]:
            next_line = re.search(r"(\d{2}\.\d{2}\.\d{4})", candidate)
            if next_line:
                return next_line.group(1)
    return ""


def date_to_iso(value: str) -> str:
    match = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", clean_text(value))
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def find_tagline_and_overview(lines: list[str], title: str) -> tuple[str, str]:
    cast_index = find_heading_index(lines, {"cast"})
    if cast_index < 0:
        return "", ""

    start = 0
    if title and title in lines:
        start = lines.index(title) + 1
    candidates = [
        line
        for line in lines[start:cast_index]
        if is_content_paragraph(line)
    ]
    if not candidates:
        return "", ""
    tagline = candidates[0]
    overview = "\n".join(candidates[1:])
    return tagline, overview


def find_story(lines: list[str]) -> str:
    story_lines = section_lines(lines, {"story", "the story"}, {"gallery", "insights"})
    paragraphs = [line for line in story_lines if is_content_paragraph(line)]
    return "\n\n".join(paragraphs)


def build_plot(overview: str, story: str) -> str:
    parts = []
    if clean_text(overview):
        parts.append(clean_text_preserving_paragraphs(overview))
    if clean_text(story):
        parts.append("Story:\n\n" + clean_text_preserving_paragraphs(story))
    return "\n\n".join(parts)


def clean_text_preserving_paragraphs(value: str) -> str:
    lines = [clean_text(line) for line in value.splitlines()]
    return "\n\n".join(line for line in lines if line)


def parse_cast_and_crew(lines: list[str]) -> tuple[list[tuple[str, list[str]]], dict[str, list[str]]]:
    cast_lines = [
        line
        for line in section_lines(lines, {"cast"}, {"video", "videos", "story", "the story"})
        if not is_noise_line(line) and line != "..."
    ]
    buckets: list[tuple[str, list[str]]] = []
    current_label = ""
    current_values: list[str] = []

    def flush() -> None:
        nonlocal current_label, current_values
        if current_label and current_values:
            buckets.append((current_label, current_values))
        current_label = ""
        current_values = []

    for line in cast_lines:
        if not current_label:
            current_label = line
            continue
        if current_values and is_likely_role_label(line):
            flush()
            current_label = line
            continue
        current_values.append(line)
    flush()

    cast: list[tuple[str, list[str]]] = []
    crew: dict[str, list[str]] = {}
    for label, values in buckets:
        normalized = label.casefold()
        if normalized in CREW_LABELS:
            crew[label] = dedupe(values)
        else:
            cast.append((label, dedupe(values)))
    return cast, crew


def is_likely_role_label(line: str) -> bool:
    normalized = clean_text(line).casefold()
    if normalized in ROLE_LABEL_HINTS or normalized in CREW_LABELS:
        return True
    if "/" in line and len(line) <= 80 and " after " not in normalized:
        return True
    if len(line.split()) <= 3 and not looks_like_person_or_group(line):
        return True
    return False


def looks_like_person_or_group(line: str) -> bool:
    text = clean_text(line)
    lower = text.casefold()
    if lower.startswith(("the ", "nnt ", "tokyo ")):
        return True
    if " and " in lower or " after " in lower:
        return True
    words = text.split()
    if len(words) < 2:
        return False
    capitalized = sum(1 for word in words if re.match(r"[A-ZÀ-Þ]", word))
    return capitalized >= 2 and len(words) <= 5


def find_video_section(lines: list[str]) -> list[OperaVisionVideo]:
    video_lines = [
        line
        for line in section_lines(lines, {"video", "videos"}, {"story", "the story", "gallery", "insights"})
        if not is_noise_line(line)
    ]
    videos: list[OperaVisionVideo] = []
    index = 0
    while index < len(video_lines):
        kind = video_lines[index]
        if kind.casefold() not in VIDEO_KINDS:
            index += 1
            continue
        title = video_lines[index + 1] if index + 1 < len(video_lines) else kind
        description_parts: list[str] = []
        index += 2
        while index < len(video_lines) and video_lines[index].casefold() not in VIDEO_KINDS:
            if is_content_paragraph(video_lines[index]):
                description_parts.append(video_lines[index])
            index += 1
        videos.append(
            OperaVisionVideo(
                kind=kind,
                title=title,
                description="\n".join(description_parts),
            )
        )
    return videos


def find_video_cards(html_text: str, base_url: str) -> list[OperaVisionVideo]:
    section = find_video_section_html(html_text)
    if not section:
        return []

    starts = list(
        re.finditer(
            r"<div\b(?=[^>]*\bclass=[\"'][^\"']*\bvideoCol\b)([^>]*)>",
            section,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    videos: list[OperaVisionVideo] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(section)
        block = section[match.start() : end]
        attrs = match.group(1)
        title = first_clean_html_match(block, r"<h3\b[^>]*>(.*?)</h3>")
        kind = first_clean_html_match(
            block, r"<span\b[^>]*class=[\"'][^\"']*\bcategory\b[^\"']*[\"'][^>]*>(.*?)</span>"
        )
        description = first_clean_html_match(
            block,
            r"<div\b[^>]*class=[\"'][^\"']*\bfield--name-field-teaser\b[^\"']*[\"'][^>]*>(.*?)</div>",
        )
        page_url = attr_value(attrs, "about") or attr_value(attrs, "id")
        if page_url and page_url.startswith("/"):
            page_url = urllib.parse.urljoin(base_url, page_url)
        youtube_id = first_attr_value(block, "data-video-id")
        external_url = f"https://www.youtube.com/watch?v={youtube_id}" if youtube_id else ""
        direct_urls = find_direct_promo_video_urls(block, base_url)
        url = direct_urls[0] if direct_urls else ""
        if title or kind or url or external_url or page_url:
            videos.append(
                OperaVisionVideo(
                    title=title or kind or title_from_video_url(url),
                    kind=kind,
                    description=description,
                    url=url,
                    page_url=page_url,
                    external_url=external_url,
                )
            )
    return videos


def find_video_section_html(html_text: str) -> str:
    match = re.search(
        r"<section\b[^>]*paragraph--type--performance-videos\b.*?</section>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(0) if match else ""


def first_clean_html_match(html_text: str, pattern: str) -> str:
    match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
    return clean_html_text(match.group(1)) if match else ""


def attr_value(attrs: str, name: str) -> str:
    pattern = rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1"
    match = re.search(pattern, attrs, flags=re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(2)) if match else ""


def first_attr_value(html_text: str, name: str) -> str:
    pattern = rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1"
    match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(2)) if match else ""


def assign_video_urls(videos: list[OperaVisionVideo], urls: list[str]) -> None:
    if not videos:
        return
    unused = list(urls)
    for video in videos:
        if video.kind.casefold() == "trailer" and unused:
            video.url = unused.pop(0)
    for video in videos:
        if not video.url and unused:
            video.url = unused.pop(0)


def section_lines(lines: list[str], starts: set[str], ends: set[str]) -> list[str]:
    start_index = find_heading_index(lines, starts)
    if start_index < 0:
        return []
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if normalize_heading(lines[index]) in ends:
            end_index = index
            break
    return lines[start_index + 1 : end_index]


def find_heading_index(lines: list[str], headings: set[str]) -> int:
    for index, line in enumerate(lines):
        if normalize_heading(line) in headings:
            return index
    return -1


def normalize_heading(line: str) -> str:
    return clean_text(line).strip("#").strip().casefold()


def is_content_paragraph(line: str) -> bool:
    text = clean_text(line)
    if len(text) < 40:
        return False
    if is_noise_line(text) or is_credit_line(text) or is_date_or_streaming_line(text):
        return False
    if normalize_heading(text) in SECTION_HEADINGS:
        return False
    return True


def is_noise_line(line: str) -> bool:
    text = clean_text(line).casefold()
    return (
        not text
        or text in NOISE_LINES
        or text.startswith("copyright")
        or text.startswith("©")
        or text == "streamed on available until recorded on"
        or text == "streamed on available until recorded on"
    )


def is_credit_line(line: str) -> bool:
    text = clean_text(line)
    return "/" in text and len(text) <= 90 and not re.search(r"[.!?]", text)


def is_image_marker(line: str) -> bool:
    return clean_text(line).casefold().startswith("image")


def is_date_or_streaming_line(line: str) -> bool:
    text = clean_text(line)
    return bool(
        re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", text)
        or "streamed on" in text.casefold()
        or "available until" in text.casefold()
        or "recorded on" in text.casefold()
        or text.casefold() == "streaming in"
    )


def find_image_urls(html_text: str, base_url: str) -> list[str]:
    urls: list[str] = []
    patterns = (
        r"https?://[^\"'<>\\\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^\"'<>\\\s]*)?",
        r"/sites/default/files/[^\"'<>\\\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^\"'<>\\\s]*)?",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, html_text, flags=re.IGNORECASE):
            url = decode_url(match.group(0))
            urls.append(urllib.parse.urljoin(base_url, url))
    return dedupe([url for url in urls if is_image_url(url)])


def find_logo_url(html_text: str, images: list[str], base_url: str) -> str:
    for url in images:
        if "logo" in urllib.parse.urlparse(url).path.casefold():
            return url

    for match in re.finditer(
        r"<a\b[^>]+href=[\"'][^\"']*/partner/[^\"']+[\"'][^>]*>(.*?)</a>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        link_images = find_image_urls(match.group(1), base_url)
        for url in link_images:
            path = urllib.parse.urlparse(url).path.casefold()
            if "header" not in path and "gallery" not in path:
                return url
    return ""


def choose_first_image(images: list[str], preferred_markers: tuple[str, ...]) -> str:
    for marker in preferred_markers:
        for url in images:
            if marker in urllib.parse.urlparse(url).path.casefold():
                return url
    return images[0] if images else ""


def find_direct_promo_video_urls(html_text: str, base_url: str) -> list[str]:
    urls: list[str] = []
    patterns = (
        r"https?://[^\"'<>\\\s]+\.mp4(?:\?[^\"'<>\\\s]*)?",
        r"/sites/default/files/[^\"'<>\\\s]+\.mp4(?:\?[^\"'<>\\\s]*)?",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, html_text, flags=re.IGNORECASE):
            url = urllib.parse.urljoin(base_url, decode_url(match.group(0)))
            if is_safe_promo_video_url(url):
                urls.append(url)
    return dedupe(urls)


def is_safe_promo_video_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.path.casefold().endswith(".mp4"):
        return False
    text = urllib.parse.unquote(parsed.path + "?" + parsed.query).casefold()
    return any(marker in text for marker in ("loop", "trailer", "teaser", "preview"))


def title_from_video_url(url: str) -> str:
    stem = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1])
    stem = re.sub(r"\.mp4$", "", stem, flags=re.IGNORECASE)
    return clean_text(stem.replace("_", " ").replace("-", " "))


def decode_url(value: str) -> str:
    text = html.unescape(value).replace("\\/", "/").replace("\\u0026", "&")
    try:
        return json.loads(f'"{text}"')
    except json.JSONDecodeError:
        return text


def is_image_url(url: str) -> bool:
    path = urllib.parse.urlparse(clean_text(url)).path.casefold()
    return bool(re.search(r"\.(?:jpg|jpeg|png|webp)$", path))


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
