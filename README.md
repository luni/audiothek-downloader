# Audiothek Downloader

This CLI downloads ARD Audiothek programs, editorial collections, or individual episodes and stores the MP3 files, cover art (16:9 + 1:1), and metadata JSON locally.

## Features

- Detects whether a URL points to a program, a curated/editorial collection, or a single episode.
- Iterates through paginated GraphQL responses to download every available episode (continues until the API says no more pages).
- Saves cover images, MP3s, and rich metadata in a predictable folder hierarchy.
- Skips files that already exist, so reruns are effectively resumable.
- Update existing folders by crawling through subdirectories and refreshing content.
- Support for direct resource IDs (URNs or numeric IDs) as an alternative to URLs.
- Refactored into a proper Python library with CLI interface.
- **Proxy support** for HTTP/HTTPS/SOCKS5 proxies.
- **Smart audio format detection** (MP3, MP4, AAC, M4A) with automatic file extension selection.
- **File modification time preservation** based on episode publish dates.
- **Intelligent re-download logic** that skips smaller files and restores incomplete downloads.
- **Content comparison** to avoid unnecessary file writes when content is unchanged.

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

# Install the package in editable mode
uv pip install -e .
```

## Usage

Get a quick overview of the available options:

```bash
audiothek --help
```

| Option        | Description                                                                                       |
| ------------- | ------------------------------------------------------------------------------------------------- |
| `--url`, `-u` | Audiothek URL (program, editorial collection, page, or single episode URN).                       |
| `--id`, `-i` | Audiothek resource ID directly (e.g. `urn:ard:episode:123456789` or `123456789`).                 |
| `--update-folders` | Update all subfolders in output directory by crawling through existing IDs.                       |
| `--folder`, `-f` | Destination directory. Defaults to `./output` (paths will be resolved absolutely). |
| `--proxy`, `-p` | Proxy URL (supports HTTP, HTTPS, and SOCKS5 proxies). |

### Download a program (all episodes)

```bash
audiothek --url 'https://www.ardaudiothek.de/sendung/j-r-r-tolkien-der-herr-der-ringe-fantasy-hoerspiel-klassiker/12197351/'
```

### Download an editorial collection

```bash
audiothek --url 'https://www.ardaudiothek.de/seite/hoerenswertes/urn:ard:page:5a615c6cb3a42c0001cfbaf8/'
```

### Download a single episode via URN

```bash
audiothek --url 'https://www.ardaudiothek.de/episode/foo/urn:ard:episode:1234567890abcdef/'
```

### Download using resource ID directly

```bash
# Download a program by numeric ID
audiothek --id '12197351'

# Download an episode by URN
audiothek --id 'urn:ard:episode:1234567890abcdef'

# Download a collection by URN
audiothek --id 'urn:ard:page:5a615c6cb3a42c0001cfbaf8'
```

### Update all existing folders

```bash
# Crawl through all subfolders in the output directory and update them
audiothek --update-folders

# Update folders in a custom directory
audiothek --update-folders --folder '/path/to/archive'
```

### Store files in a custom directory

```bash
audiothek \
  --url 'https://www.ardaudiothek.de/sendung/example/12345678/' \
  --folder '/path/to/archive'
```

### Use a proxy

```bash
# HTTP proxy
audiothek --url 'https://example.com/audiothek-url' --proxy 'http://proxy.example.com:8080'

# SOCKS5 proxy
audiothek --url 'https://example.com/audiothek-url' --proxy 'socks5://proxy.example.com:1080'
```

## Development

### Running as Module

You can also run the package as a Python module:

```bash
uv run python -m audiothek --help
uv run python -m audiothek --url 'https://example.com/audiothek-url'
```

### Using as a Library

The refactored code can be used as a Python library:

```python
from audiothek import AudiothekDownloader, AudiothekClient

# Create downloader instance
downloader = AudiothekDownloader("/path/to/output")

# Download from URL
downloader.download_from_url("https://www.ardaudiothek.de/sendung/example/12345678/")

# Download from ID
downloader.download_from_id("urn:ard:episode:1234567890abcdef", "/path/to/output")

# Update existing folders
downloader.update_all_folders("/path/to/archive")

# Use the client directly for API operations
client = AudiothekClient()
program_data = client.fetch_program_set_data("12345678")
```

### Testing

Run the test suite:

```bash
uv run make test
```

The project maintains 90%+ test coverage with 177 passing tests.

## Output structure

Episodes are grouped by program set ID inside the chosen folder:

```
output/
  <program_set_id>/
    <slug>_<episode_id>.mp3/.mp4/.m4a/.aac  # Audio file with correct extension
    <slug>_<episode_id>.jpg        # 16:9 cover
    <slug>_<episode_id>_x1.jpg     # 1:1 cover
    <slug>_<episode_id>.json       # metadata (title, summary, duration, publish date, etc.)
```

## GraphQL queries

The script relies on the public `https://api.ardaudiothek.de/graphql` endpoint and ships the queries in the `src/audiothek/graphql/` directory:

- `ProgramSetEpisodesQuery.graphql` for regular shows
- `editorialCollection.graphql` for curated collections
- `EpisodeQuery.graphql` for single episodes

You can tweak these documents if ARD changes their API structure.

## Notes & limitations

1. Only episodes that expose a `downloadUrl` (or fallback `url`) can be saved—DRM-protected content may not download.
2. Large feeds are paginated in batches of 24 items; the downloader loops until `hasNextPage` is `false`.
3. Respect ARD Audiothek's terms of service and only download content you are allowed to store locally.
4. The `--update-folders` functionality replaces the previous `scrape.sh` script for updating existing downloads.
5. The project has been refactored into a proper Python package with a clean separation between library code and CLI interface.
6. **Audio files are automatically assigned the correct extension** based on the URL format (.mp3, .mp4, .m4a, .aac).
7. **File modification times are set** to match the episode's publish date for better organization.
8. **Incomplete downloads are automatically detected** and re-downloaded, with smaller files being skipped to save bandwidth.
9. **Proxy support is available** for users behind corporate firewalls or in regions with restricted access.
