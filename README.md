# Live Performance Metadata and Extras Getter by mp3li

Live Performance Metadata and Extras Getter by mp3li is a command-line tool for turning supported public performance detail pages into Jellyfin-ready local metadata folders.

It scrapes detail pages and saves title folders inside `Output`. Manual mode previews each result before saving; import mode reads `mylinks.txt` and saves every non-skipped entry automatically. The saved folder can include:

- a Jellyfin-style `.nfo` metadata file
- poster art
- wide artwork saved as `fanart`, `banner`, and `landscape`
- production logo art when available
- trailers saved under `trailers`
- OperaVision gallery images saved under `extras/gallery`
- OperaVision video-section extras saved under `extras/videos`

The tool is meant for supported provider detail pages, not arbitrary playable media URLs. You paste a page like an Amazon Prime Video detail page, an OperaVision performance page, a BroadwayHD video page, a Netflix title page, or a Metropolitan Opera Livestream broadcast page, review what was found, and then choose whether to save it.

## Run Command

Run the tool with:

```bash
cd "/path/to/Live Performance Metadata and Extras Getter by mp3li"
python3 live_performance_metadata_and_extras_getter.py
```

The tool creates and uses this folder automatically:

```text
Output
```

## Optional Dependency For Embedded Extra Videos

Direct `.mp4` trailers and direct `.mp4` extras can be downloaded with the Python standard library and macOS `curl`.

Embedded extras, such as OperaVision YouTube embeds, need `yt-dlp` so they can be saved as real `.mp4` files instead of links. Install it with:

```bash
python3 -m pip install --user yt-dlp
```

The tool does not save `.strm` files.

## How The Prompt Works

When you start the tool, it prints the welcome text and asks:

```text
Would you like to import your mylinks.txt or manually insert links here?
1. Import your mylinks.txt
2. Manually insert links here
Choose 1 or 2:
```

Choose `1` to import links from:

```text
My Links Txt/mylinks.txt
```

Import mode processes the whole file automatically. It skips entries that already have Output folders and saves the rest without showing previews or asking one by one.

Choose `2` to paste links manually. Manual mode keeps the same link prompt:

```text
Paste your detail page link:
```

Paste one detail-page URL and press Enter. For each manually pasted link, the tool will:

1. fetch the detail page/provider data
2. run the matching supported provider scraper
3. show a preview of the title, dates, cast, studio/production, ratings, plot, artwork status, trailer status, gallery status, and extra-video status
4. ask whether to save the title folder
5. save the `.nfo`, images, trailer, and extras if you answer yes
6. ask whether you want to paste another link

After each link, it asks:

```text
Would you like to paste another link? [Y/N]:
```

Choose `Y` to paste another detail page. Choose `N` to finish.

## Importing My Links Txt/mylinks.txt

The import file must be named exactly:

```text
mylinks.txt
```

and it must live in this folder:

```text
My Links Txt
```

The simplest entry format is just a link:

```text
https://example.com/detail-page

https://example.com/next-detail-page
```

You can also put an optional label above a link:

```text
Title/Production:
https://example.com/detail-page

Any label you want, even a messy note
https://example.com/next-detail-page
```

That means:

- a link by itself is valid
- an optional label line above a link is valid
- the optional label can end with `:`, but it does not have to
- blank lines between entries are fine
- the link must start with `http://` or `https://`
- labels are only human notes; the saved title and production are always scraped from the detail page itself

Import mode skips entries that already have an Output folder. It checks existing `.nfo` source/detail links first, then also checks the computed title folder after scraping the page. Entries that are not skipped are saved automatically.

## Manual Review Before Save

In manual mode, nothing is saved until after the preview is shown and you answer yes to:

```text
Save this title folder? [Y/n]:
```

The preview shows found/not-found style statuses for images and videos instead of printing long media URLs. Image and trailer URLs are useful internally for downloading assets, but they are not written into the `.nfo`.

## Output Folder Layout

Each saved title gets its own folder inside `Output`.

The folder name uses:

```text
Title - Studio
```

or:

```text
Title - Production
```

depending on what the page provides.

Example:

```text
Output/Shrek the Musical - Fox/
```

Inside that folder, the `.nfo` and local artwork use the same base filename:

```text
Output/Shrek the Musical - Fox/Shrek the Musical - Fox.nfo
Output/Shrek the Musical - Fox/Shrek the Musical - Fox-poster.jpg
Output/Shrek the Musical - Fox/Shrek the Musical - Fox-fanart.jpg
Output/Shrek the Musical - Fox/Shrek the Musical - Fox-banner.jpg
Output/Shrek the Musical - Fox/Shrek the Musical - Fox-landscape.jpg
Output/Shrek the Musical - Fox/trailers/trailer.mp4
```

OperaVision pages can also include production logos, galleries, and video extras:

```text
Output/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025.nfo
Output/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025-logo.png
Output/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025/extras/gallery/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025-gallery-01.jpg
Output/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025/extras/videos/Sneek Peek at The Nutcracker.mp4
Output/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025/extras/videos/Behind the scenes of The Nutcracker.mp4
```

## Jellyfin Naming Notes

The tool uses Jellyfin-friendly local metadata names:

- `.nfo` file: saved beside the title assets using the folder/title base name
- poster: `Title - Studio-poster.jpg`
- fanart: `Title - Studio-fanart.jpg`
- banner: `Title - Studio-banner.jpg`
- landscape: `Title - Studio-landscape.jpg`
- logo: `Title - Studio-logo.png`
- trailer: `trailers/trailer.mp4`
- gallery extras: `extras/gallery/...`
- video extras: `extras/videos/...`

The extras folders use lowercase names because Jellyfin documents folder names like `extras` and `trailers` in lowercase.

OperaVision output uses a more specific bundle name when the page exposes the right fields:

- `Title  ⁄  Composer - Production Year`

Other providers keep the normal `Title - Studio` or `Title - Production` folder naming.

## Metadata Written To The NFO

The generated `.nfo` uses a `<movie>` root, which Jellyfin can read for standalone movie or music-video-style library items.

The tool writes known fields such as:

- title
- original title
- sort title
- plot/overview
- tagline
- year
- premiered/aired/release date
- runtime
- ratings
- content rating
- language
- genres
- tags
- countries
- studios/production
- directors
- writers
- credits/producers/composers
- cast with roles when available
- source site
- detail link you pasted
- fetched/canonical source URL

Additional scraped fields that do not map cleanly to a standard tag are preserved inside XML comments in the `.nfo`.

## Source Tracking

Each `.nfo` keeps track of where the metadata came from:

```xml
<source_site>...</source_site>
<detail_link>...</detail_link>
<source_url>...</source_url>
```

This makes it easier to trace a saved folder back to the exact page you pasted.

## Code Layout

The root script is only a launcher:

```text
live_performance_metadata_and_extras_getter.py
```

The main code lives in:

```text
Base Script/live_performance_metadata_and_extras_getter_base.py
```

Provider-specific code lives in:

```text
Provider Scripts/
```

The tool only accepts links for providers that have a provider script in that folder.

If you paste a link for a provider that is not supported yet, the tool prints:

```text
Unfortunately this tool does not cover that provider at this time. Please make an Issue on Github for a Feature Request.
```

## Supported Site-Specific Scrapers

### Amazon Prime Video

Amazon pages are handled by:

```text
Provider Scripts/amazon.py
```

The Amazon helper looks for:

- title
- year
- runtime
- content rating
- studio
- genres
- directors
- producers
- cast
- Amazon rating
- IMDb rating
- plot/description
- cover art
- wide art
- trailer target metadata when exposed by the page

Some Amazon detail pages expose different HTML depending on the provider, such as BroadwayHD or Marquee TV. The Amazon helper has specific logic for those detail-page layouts.

### OperaVision

OperaVision pages are handled by:

```text
Provider Scripts/operavision.py
```

The OperaVision helper looks for:

- production/company
- title
- composer
- streamed date
- available-until date
- recorded date
- tagline
- overview
- story section
- cast roles
- creative credits
- production logo
- poster/header image
- wide image
- gallery images
- on-page video cards
- direct autoplay trailer/background MP4

OperaVision video cards are counted from the page's `Videos` section. If the cards are YouTube embeds, the tool uses `yt-dlp` to download each one as an `.mp4` file into `extras/videos`.

### BroadwayHD

BroadwayHD pages are handled by:

```text
Provider Scripts/broadwayhd.py
```

Supported links look like:

```text
https://broadwayhd.com/video/897550?showInterstitial=true
```

The BroadwayHD helper reads the public app data used by the page and looks for:

- title
- runtime
- genre
- year
- description
- cast
- director and film director
- book
- music and lyrics
- producers and executive producers
- poster artwork
- wide backdrop artwork
- logo artwork
- trailer target when exposed by the page

BroadwayHD does not always expose a separate studio or production field, so the tool uses `BroadwayHD` as the provider/studio fallback for folder naming. Trailer downloading is best-effort and only saves a trailer file if the page exposes a direct public `.mp4`.

### Netflix

Netflix title pages are handled by:

```text
Provider Scripts/netflix.py
```

Supported links look like:

```text
https://www.netflix.com/title/82719754
```

The Netflix helper reads the public structured page data and looks for:

- title
- year
- content rating
- description
- genres
- tags
- cast
- starring list
- directors
- poster artwork
- wide artwork
- logo artwork
- trailer target when exposed by the page

The Netflix helper uses the public HTML shell, JSON-LD, and embedded app data instead of guessing from rendered text.

### Metropolitan Opera Livestream

Metropolitan Opera Livestream broadcast pages are handled by:

```text
Provider Scripts/metopera.py
```

Supported links look like:

```text
https://ondemand.metopera.org/broadcast/9ce1e692-36ed-464c-b06b-551d55dfff56
```

The provider reads the public Met Opera On Demand middleware data for the currently playing broadcast item and looks for:

- title
- performance date
- runtime
- composer
- librettist
- conductor
- cast and roles
- orchestra/chorus ensemble
- short page description
- full act-by-act synopsis from the Full Synopsis link
- world premiere line from the synopsis page
- current track when cue-point data is available
- poster/wide artwork
- Met Opera ID

For Met livestream pages, the NFO writes the shorter Met page description to `<outline>` and writes the longer description plus full synopsis and world-premiere line to `<plot>`.

## Separate Livestream Audio Tool

Full livestream audio capture is handled by a separate standalone tool:

```text
/path/to/The Metropolitan Opera Livestream Getter by mp3li
```

Run it with:

```bash
cd "/path/to/The Metropolitan Opera Livestream Getter by mp3li"
python3 the_metropolitan_opera_livestream_getter.py
```

That tool prompts for the Met broadcast page link, captures `master.m3u8` and `rendition.m3u8` from browser network traffic, saves the MP3, then writes its own Jellyfin-style `.nfo` and artwork in the same title folder.

## What The Tool Does Not Do

The tool does not:

- save `.strm` files
- write image URLs or trailer URLs into the `.nfo`
- ask where to save output
- save into your Jellyfin media folders directly
- scrape private account data
- bypass DRM

Everything goes into the local `Output` folder first so you can inspect it before moving files into your media library.

## Existing Output

The current `Output` folder already uses the title-folder layout. For example:

```text
Output/Don Giovanni  ⁄  Mozart - Opera Ballet Vlaanderen 2025/
Output/The Nutcracker  ⁄  Tchaikovsky - New National Theatre Tokyo 2025/
Output/Shrek the Musical - Fox/
Output/Merrily We Roll Along - Netflix/
```

Those folders can be copied or moved beside matching media files later if you want Jellyfin to pick them up next to local video files.

## Troubleshooting

If a page opens in your browser but the tool cannot get much data, the page may be filling important fields with JavaScript after load. The tool reads the HTML returned by the page request and then applies site-specific parsing where supported.

If an embedded extra video does not appear as an `.mp4`, make sure `yt-dlp` is installed:

```bash
python3 -m pip install --user yt-dlp
```

If artwork is missing, the page may not expose a usable image URL in the returned HTML.

If a site uses DRM or protected streaming for actual playable content, the tool should not try to download that protected content. It is intended for metadata, trailers, public images, galleries, and public extra videos.
