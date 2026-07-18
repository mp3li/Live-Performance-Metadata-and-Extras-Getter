# Changelog

All notable changes to Live Performance Metadata and Extras Getter by mp3li are
documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- A MarqueeTV provider parser for public detail pages, including title, cast,
  crew, artwork, trailer, and gallery extraction.
- A Disney+ provider parser for public browse entity pages, including title,
  descriptions, rating, runtime, genres, director, cast, and artwork
  extraction.
- An explicit, non-interactive `--handoff` mode for a compatible local
  downloader extension on macOS.
- `--detail-link`, `--media-folder`, and required `--skip-existing` handoff
  arguments, so a completed download folder can receive metadata and extras
  using this project's existing provider parsers and local settings.
- Handoff-sidecar renaming that keeps externally downloaded Jellyfin subtitles
  matched to the final video filename when a generic `master-...` video is
  renamed.

### Changed

- The existing generic `master-...` video rename behavior can now run before
  handoff sidecars are written, keeping NFO and artwork names aligned with the
  final video filename.
- Generic rename detection now also covers random timestamped provider download
  basenames, and MarqueeTV metadata now uses title-only bundle naming instead of
  `Title - MarqueeTV`.

### Safety

- Handoff requires exactly one direct video in the supplied folder, rejects
  invalid/unsupported/ambiguous input before output work, and skips existing
  matching metadata or artwork without overwriting it.
- The normal no-argument launcher and interactive standalone workflow remain
  unchanged.
