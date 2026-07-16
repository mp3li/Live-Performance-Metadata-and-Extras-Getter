<h1 align="center">Live Performance Metadata and Extras Getter by mp3li</h1>

<p align="center">
  A macOS Python tool for turning supported public performance detail pages into local metadata folders that work cleanly with Jellyfin libraries.
</p>

<p align="center">
  <img alt="Status" src="https://img.shields.io/badge/Status-In_Active_Development-660000?style=flat-square&labelColor=04040c" />
  <img alt="Interface" src="https://img.shields.io/badge/Interface-Terminal-660000?style=flat-square&labelColor=04040c" />
  <img alt="Metadata" src="https://img.shields.io/badge/Metadata-Jellyfin_Style_NFO-660000?style=flat-square&labelColor=04040c" />
  <img alt="Providers" src="https://img.shields.io/badge/Providers-Amazon_Prime_OperaVision_Metropolitan_Opera_BroadwayHD_%26_Netflix-660000?style=flat-square&labelColor=04040c" />
  <img alt="Downloads" src="https://img.shields.io/badge/Downloads-Images%2C_Trailers%2C_Extras_%26_Metadata-660000?style=flat-square&labelColor=04040c" />
  <img alt="Bulk Processing" src="https://img.shields.io/badge/Bulk_Processing-Optional-660000?style=flat-square&labelColor=04040c" />
  <img alt="Platform" src="https://img.shields.io/badge/Platform-macOS_Tahoe-660000?style=flat-square&labelColor=04040c" />
</p>

## Table of Contents

<details>
<summary>Open Table of Contents</summary>

<br />

- [About the Project](#about-the-project)
- [What the Tool Does](#what-the-tool-does)
- [Supported Providers](#supported-providers)
- [Requirements](#requirements)
- [How to Run](#how-to-run)
- [Optional Downloader Handoff](#optional-downloader-handoff)
- [How to Use the Tool](#how-to-use-the-tool)
- [Importing mylinks.txt](#importing-mylinkstxt)
- [Settings](#settings)
- [Media Matching](#media-matching)
- [Output Structure and Jellyfin Naming](#output-structure-and-jellyfin-naming)
- [Metadata Written to the NFO](#metadata-written-to-the-nfo)
- [Optional Dependency for Embedded Extra Videos](#optional-dependency-for-embedded-extra-videos)
- [Platform Notes](#platform-notes)
- [Known Limitations](#known-limitations)
- [Project Structure](#project-structure)
- [Documentation Map](#documentation-map)
- [Responsible Use and Accommodation Disclaimer](#responsible-use-and-accommodation-disclaimer)

</details>

## About the Project

Live Performance Metadata and Extras Getter by mp3li is a macOS Python tool for turning supported public performance detail pages into local metadata folders that work cleanly with Jellyfin libraries.

The tool is built around a practical workflow:

- paste a supported detail page link
- scrape structured metadata with a provider-specific parser
- preview the result in manual mode
- save a `.nfo`, images, trailer, and extras into one title folder
- optionally match an existing media folder and name saved files from the real video filename
- optionally bulk process multiple links from `mylinks.txt`

It is meant for supported provider detail pages, not direct playable stream URLs and not arbitrary websites.

## What the Tool Does

- Scrapes supported provider detail pages.
- Builds Jellyfin-style `.nfo` metadata.
- Saves the source site, pasted detail link, and fetched source URL into the `.nfo`.
- Downloads poster art when available.
- Downloads wide artwork and saves it as `fanart`, `banner`, and `landscape`.
- Downloads logo art when available.
- Downloads direct trailers when available.
- Downloads supported gallery images and extra videos when available.
- Can import multiple links from a text file or accept manual one-by-one link entry.
- Can optionally match existing media folders and save files beside the real media.
- Can rename a generic downloader video filename, such as `master-...`, before writing matching metadata and artwork files.

## Supported Providers

The provider scripts currently documented for this tool are:

- Amazon Prime Video detail pages
- OperaVision performance pages
- BroadwayHD video pages
- Netflix title pages

Unsupported providers do not fall back to generic scraping. The tool prints:

```text
Unfortunately this tool does not cover that provider at this time. Please make an Issue on Github for a Feature Request.
```

## Requirements

To run this tool as documented right now, you need:

- **macOS**  
  This tool is currently supported on macOS only.
- **Python 3**  
  The launcher is run with `python3`.
- **Internet access**  
  The tool fetches supported provider detail pages, metadata, images, and any available direct trailer or extras files.
- **A supported provider link**  
  The tool only works with providers that already have a provider script in this project.

Optional but useful:

- **`yt-dlp`**  
  Needed only for some embedded extra videos where the provider page exposes the extra through an embedded player instead of a direct file URL.

Windows and Linux support is planned, but they are not supported yet in the current documented release.

## How to Run

Run the launcher with:

```bash
cd "/path/to/Live Performance Metadata and Extras Getter by mp3li"
python3 "Launchers/live_performance_metadata_and_extras_getter.py"
```

By default, the tool saves output into:

```text
Output
```

## Optional Downloader Handoff

This project remains fully standalone: the normal launcher command above starts
the existing interactive workflow unchanged. On macOS, a compatible locally
installed downloader extension can optionally call LPMAEG only after its own
download, subtitle work, and cleanup have completed.

That handoff supplies a supported **public detail-page link** and the folder
containing the completed media. It never uses a stream or manifest URL. LPMAEG
requires exactly one video directly in that folder, uses this project's normal
local settings for NFO, artwork, trailer, and extras behavior, and skips rather
than overwrites existing matching metadata or artwork.

The extension normally generates this command for you. For an intentional
manual handoff, run:

```bash
cd "/path/to/Live Performance Metadata and Extras Getter by mp3li"
python3 "Launchers/live_performance_metadata_and_extras_getter.py" \
  --handoff \
  --detail-link "https://supported-provider.example/detail-page" \
  --media-folder "/absolute/path/to/completed-download-folder" \
  --skip-existing
```

Invalid or unsupported links, zero or multiple videos, and scrape failures
return an error without changing the video. A generic downloader filename such
as `master-...` may be renamed using LPMAEG's existing media naming behavior
before matching sidecars are written.

## How to Use the Tool

When the tool starts, it prints:

```text
Welcome to Live Performance Metadata and Extras Getter by mp3li

This tool scrapes publicly available detail pages from supported providers and turns them into Jellyfin-style .nfo metadata. It also downloads available trailers and images, names them with Jellyfin-friendly artwork filenames, and saves everything in the Output folder.

Would you like to import your mylinks.txt or manually insert links here?
1. Import your mylinks.txt
2. Manually insert links here
Choose 1 or 2:
```

### Manual mode

Choose `2` to paste one supported detail page link at a time.

Manual mode:

- fetches the page
- runs the matching provider parser
- shows a preview before saving
- asks whether to save the title folder
- asks whether you want to paste another link

The related prompts are:

```text
Paste your detail page link:
Save this title folder? [Y/n]:
Would you like to paste another link? [Y/N]:
```

When saving starts, the tool shows:

```text
Creating your .nfo file and grabbing your trailer/images
```

### Import mode

Choose `1` to load links from:

```text
My Links Txt/mylinks.txt
```

Import mode processes the file automatically. It does not show one-by-one save prompts. It skips entries the tool detects as already handled and saves the rest.

## Importing mylinks.txt

The real import file must be named exactly:

```text
mylinks.txt
```

and it must live here:

```text
My Links Txt/
```

The repo includes a safe example file here:

```text
My Links Txt/mylinks-default.txt
```

To use it, remove `-default` from the filename.

Rules:

- links must start with `http://` or `https://`
- optional text above a link is okay
- blank text that is not a link will not be counted
- blank lines between entries are fine
- text above a link is only a note for you
- the saved metadata still comes from the provider page itself

Example:

```text
The Nutcracker / OperaVision:
https://example.com/operavision-detail-page

Messy note text that is not the real title
https://example.com/another-detail-page
```

## Settings

Tracked default settings live here:

```text
Settings/settings-default.json
```

To use your own live settings file:

1. copy or rename `settings-default.json`
2. make it `settings.json`
3. keep it in the same `Settings` folder

The real local `Settings/settings.json` is gitignored.

### `output_dir`

This tells the tool where to put saved folders when it is not saving beside matched media.

Default:

```json
"output_dir": "Output"
```

### `downloads`

This group controls what kinds of files the tool tries to save.

#### `images`

Turns poster, wide artwork, and logo downloading on or off.

Options:

- `true` = download available images
- `false` = do not download images

#### `trailers`

Turns trailer downloading on or off.

Options:

- `true` = download available trailers
- `false` = do not download trailers

#### `gallery_images`

Turns gallery image downloading on or off.

Options:

- `true` = download gallery images when a provider page offers them
- `false` = skip gallery images

#### `extra_videos`

Turns extra video downloading on or off.

Options:

- `true` = download extra videos when possible
- `false` = skip extra videos

#### `trailers_folder`

This is the folder name used for trailers inside each saved title folder.

Default:

```json
"trailers_folder": "trailers"
```

#### `extras_folder`

This is the main folder name used for extra downloaded items such as extra videos.

Default:

```json
"extras_folder": "extras"
```

#### `gallery_folder`

This is the folder name used for gallery images.

Default:

```json
"gallery_folder": "extrafanart"
```

#### `extra_videos_folder`

This is the fallback folder name used for extra videos when the tool does not sort them into a more specific folder such as `interviews` or `behind the scenes`.

Default:

```json
"extra_videos_folder": "extras"
```

### `media_matching`

This group controls whether the tool tries to find your real media folders and place files beside them.

#### `enabled`

Turns media matching on or off.

Options:

- `true` = search your chosen media roots for matching folders or files
- `false` = save normally into the general output folder

Default:

```json
"enabled": false
```

#### `media_roots`

This is the list of folders the tool is allowed to search when media matching is enabled.

Example:

```json
"media_roots": [
  "/Volumes/DriveName/Movies",
  "/Users/you/Media"
]
```

#### `save_to_matched_media_folder`

Tells the tool whether it should actually save into the matched media folder after finding it.

Options:

- `true` = save into the matched media folder
- `false` = only use matching for detection logic, then still save to the normal output folder

#### `rename_matched_folders`

Tells the tool whether it is allowed to rename matched media folders when the naming rules call for it.

Options:

- `true` = allow folder renaming
- `false` = do not rename matched folders

#### `match_threshold`

This controls how close a folder name or filename has to be before the tool treats it as a match.

Lower values are looser. Higher values are stricter.

Default:

```json
"match_threshold": 0.88
```

#### `scan_subfolders`

Controls whether the tool searches only the top level of your media roots or also searches deeper folders inside them.

Options:

- `true` = search inside subfolders
- `false` = only search the top level

## Media Matching

Media matching is the feature that lets the tool place metadata files, artwork files, trailers, and extras beside your actual video files instead of only saving into the general `Output` folder.

By default, this feature is off:

```json
"enabled": false
```

When it is off:

- the tool saves into `Output`
- folder names are based on the scraped metadata bundle name

When it is on:

- the tool searches the folders listed in `media_roots`
- if it finds a strong enough match, it can save directly into that real media folder
- if it does not find a match, it falls back to the normal output folder

This is useful because Jellyfin expects metadata files and artwork files to match the real media filename when you want those local files to be picked up automatically. This tool uses the video filename on purpose so the saved files stay directly usable and easier to keep organized.

## Output Structure and Jellyfin Naming

If there is no matched media folder, the tool saves into `Output/<title folder>`.

If media matching is enabled and a matching folder is found, the tool can save beside the real media instead.

### When saving into a matched media folder

The real video filename becomes the naming anchor.

That means:

- the `.nfo` filename matches the video filename
- poster, fanart, banner, landscape, and logo filenames match the video filename
- trailers go in the configured trailers folder
- gallery images go in `extrafanart`
- extra videos go in `extras` or a more specific extras subfolder

### When saving into Output

The tool uses the computed title bundle name for the folder and saved files.

Examples:

```text
Output/Shrek the Musical - Fox/Shrek the Musical - Fox.nfo
Output/Shrek the Musical - Fox/Shrek the Musical - Fox-poster.jpg
Output/Shrek the Musical - Fox/Shrek the Musical - Fox-fanart.jpg
Output/Shrek the Musical - Fox/Shrek the Musical - Fox-banner.jpg
Output/Shrek the Musical - Fox/Shrek the Musical - Fox-landscape.jpg
Output/Shrek the Musical - Fox/trailers/trailer.mp4
```

OperaVision uses the more specific bundle naming the tool was configured to produce, for example:

```text
Forest Song  ⁄  Skorulskyi - Dnipro Academic Opera and Ballet Theatre 2025
```

### Extras layout

- gallery images go in `extrafanart`
- extra videos go in `extras`
- extra video groups may be split into folders such as:
  - `interviews`
  - `clips`
  - `featurettes`
  - `behind the scenes`
  - `deleted scenes`
  - `trailers`

## Metadata Written to the NFO

The generated `.nfo` uses a `<movie>` root and writes fields such as:

- title
- original title
- sort title
- plot / overview
- tagline
- year
- premiered / aired / release date
- runtime
- ratings
- content rating
- language
- genres
- tags
- countries
- studios / production
- directors
- writers
- credits / producers / composers
- cast, with roles when available
- source site
- pasted detail link
- fetched / canonical source URL

Additional non-standard scraped fields are preserved in XML comments so they are not silently lost.

## Optional Dependency for Embedded Extra Videos

If a detail page includes embedded videos such as behind-the-scenes features, interview clips, or similar extras, the tool may need `yt-dlp` to turn those embedded pages into real local `.mp4` files.

It is not needed if you only want `.nfo` files, text metadata, and image downloads.

Install it with:

```bash
python3 -m pip install --user yt-dlp
```

The tool does not save `.strm` files.

## Platform Notes

This tool was developed on **macOS Tahoe** and browser testing during development was done in **Firefox**.

The project also currently contains macOS-oriented assumptions, including:

- macOS-style Google Chrome app path usage for browser-assisted flows
- macOS `curl` fallback behavior during some download steps

Because of that, this tool is currently **macOS-only** in practice and in documentation.

Windows and Linux support is planned, but it has not been implemented and tested for release yet.

## Known Limitations

- Only supported providers work.
- Site changes can break a provider script until it is updated.
- Trailer and extra-video download success depends on whether the provider exposes a real downloadable media URL.
- The tool does not download DRM-protected trailers or other DRM-protected media.
- Some provider pages expose incomplete metadata even when the visible page looks richer.
- Media matching is intentionally careful. If the match is weak, the tool falls back to normal output instead of guessing aggressively.

## Project Structure

```text
Launchers/
  live_performance_metadata_and_extras_getter.py

Base Script/
  live_performance_metadata_and_extras_getter_base.py

Provider Scripts/
  amazon.py
  broadwayhd.py
  metopera.py
  netflix.py
  operavision.py

Settings/
  settings-default.json

My Links Txt/
  mylinks-default.txt
```

## Documentation Map

- `README.md` - public overview, run instructions, settings explanation, and naming rules
- `Launchers/live_performance_metadata_and_extras_getter.py` - launcher entry point
- `Base Script/live_performance_metadata_and_extras_getter_base.py` - main tool logic
- `Provider Scripts/` - provider-specific scraping logic
- `Settings/settings-default.json` - tracked default settings
- `My Links Txt/mylinks-default.txt` - tracked example import file

## Responsible Use and Accommodation Disclaimer

This tool is provided for educational, research, and accessibility or accommodation support purposes only.

It does not bypass DRM, does not obtain DRM-protected material, and does not access page information that requires a logged-in session when that information is not publicly visible to the tool.

You are responsible for how you use this project, what material you process with it, and whether your use complies with the laws, licenses, and terms that apply to you. The author is not responsible for misuse.
