# Audiothek Downloader

This CLI downloads ARD Audiothek programs, editorial collections, or individual episodes and stores the MP3 files, cover art (16:9 + 1:1), and metadata JSON locally.

## Features

- Detects whether a URL points to a program, a curated/editorial collection, or a single episode.
- Iterates through paginated GraphQL responses to download every available episode (continues until the API says no more pages).
- Saves cover images, MP3s, and rich metadata in a predictable folder hierarchy.
- Skips files that already exist, so reruns are effectively resumable.

## Requirements

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/) for dependency management (recommended; project tooling assumes it).

## Installation

```bash
git clone https://github.com/luni/audiothek-downloader.git
cd audiothek-downloader

# Install uv if you do not have it yet
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create the virtual environment and install dependencies
uv sync
```

## Usage

Get a quick overview of the available options:

```bash
uv run python audiothek.py --help
```

| Option        | Description                                                                                       |
| ------------- | ------------------------------------------------------------------------------------------------- |
| `--url`, `-u` | Required. Audiothek URL (program, editorial collection, page, or single episode URN).             |
| `--folder`, `-f` | Optional. Destination directory. Defaults to `./output` (paths will be resolved absolutely). |

### Download a program (all episodes)

```bash
uv run python audiothek.py --url 'https://www.ardaudiothek.de/sendung/j-r-r-tolkien-der-herr-der-ringe-fantasy-hoerspiel-klassiker/12197351/'
```

### Download an editorial collection

```bash
uv run python audiothek.py --url 'https://www.ardaudiothek.de/seite/hoerenswertes/urn:ard:page:5a615c6cb3a42c0001cfbaf8/'
```

### Download a single episode via URN

```bash
uv run python audiothek.py --url 'https://www.ardaudiothek.de/episode/foo/urn:ard:episode:1234567890abcdef/'
```

### Store files in a custom directory

```bash
uv run python audiothek.py \
  --url 'https://www.ardaudiothek.de/sendung/example/12345678/' \
  --folder '/path/to/archive'
```

## Output structure

Episodes are grouped by program set ID inside the chosen folder:

```
output/
  <program_set_id>/
    <slug>_<episode_id>.mp3
    <slug>_<episode_id>.jpg        # 16:9 cover
    <slug>_<episode_id>_x1.jpg     # 1:1 cover
    <slug>_<episode_id>.json       # metadata (title, summary, duration, publish date, etc.)
```

## GraphQL queries

The script relies on the public `https://api.ardaudiothek.de/graphql` endpoint and ships the queries in the `graphql/` directory:

- `ProgramSetEpisodesQuery.graphql` for regular shows
- `editorialCollection.graphql` for curated collections
- `EpisodeQuery.graphql` for single episodes

You can tweak these documents if ARD changes their API structure.

## Notes & limitations

1. Only episodes that expose a `downloadUrl` (or fallback `url`) can be saved—DRM-protected content may not download.
2. Large feeds are paginated in batches of 24 items; the downloader loops until `hasNextPage` is `false`.
3. Respect ARD Audiothek’s terms of service and only download content you are allowed to store locally.
