# ARD Audiothek Downloader

A powerful Python tool for downloading content from the ARD Audiothek platform. Download entire programs, editorial collections, or individual episodes with metadata, cover art, and audio files in the highest available quality.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Features

- **Smart Content Detection**: Automatically identifies programs, collections, or episodes from URLs or IDs
- **Complete Collection Download**: Downloads all episodes from a program or collection with pagination support
- **High Quality Media**: Selects the highest quality audio available (MP3, MP4, AAC, M4A)
- **Rich Metadata**: Preserves episode details, publish dates, and cover images
- **Efficient Updates**: Only downloads new or updated content
- **Intelligent File Management**:
  - Preserves file modification times based on publish dates
  - Automatically selects correct file extensions
  - Compares content to avoid unnecessary writes
  - Re-downloads incomplete files while preserving originals
  - Skips smaller/lower quality files when better versions exist
- **Network Features**:
  - Support for HTTP/HTTPS/SOCKS5 proxies
  - Fallback URL support when primary sources fail
- **Flexible Usage**: Command-line interface and Python library API

## Installation

### Requirements

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) for dependency management

### Setup

```bash
# Clone the repository
git clone https://github.com/luni/audiothek-downloader.git
cd audiothek-downloader

# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync

# Install the package in development mode
uv pip install -e .
```

## Command-Line Usage

### Basic Commands

```bash
# Get help
audiothek --help

# Download a program (all episodes)
audiothek --url 'https://www.ardaudiothek.de/sendung/example-program/12345678/'

# Download a single episode
audiothek --url 'https://www.ardaudiothek.de/episode/example/urn:ard:episode:1234567890abcdef/'

# Download using direct ID
audiothek --id 'urn:ard:episode:1234567890abcdef'

# Update all existing downloads
audiothek --update-folders
```

### Command Options

| Option | Description |
|--------|-------------|
| `--url`, `-u` | ARD Audiothek URL to download |
| `--id`, `-i` | Direct resource ID (URN or numeric) |
| `--folder`, `-f` | Output directory (default: `./output`) |
| `--cache-dir` | Directory for the on-disk GraphQL response cache (default: `~/.cache/audiothek-downloader`) |
| `--update-folders` | Update all existing downloads in the output directory |
| `--migrate-folders` | Migrate folders to new naming schema (ID + Title) |
| `--remove-lower-quality` | Remove lower quality files when higher quality exists |
| `--editorial-category-id` | Search by editorial category ID |
| `--search-type` | Filter type for editorial category search |
| `--max-workers` | Maximum number of parallel download workers (default: 4, max: 16) |
| `--proxy`, `-p` | Proxy URL for network requests |
| `--dry-run` | Show what would be done without making changes |

## Advanced Usage

### Custom Output Directory

```bash
audiothek --url 'https://www.ardaudiothek.de/sendung/example/12345678/' --folder '/path/to/archive'
```

### Using a Proxy

```bash
# HTTP proxy
audiothek --url 'https://example.com/audiothek-url' --proxy 'http://proxy.example.com:8080'

# SOCKS5 proxy
audiothek --url 'https://example.com/audiothek-url' --proxy 'socks5://proxy.example.com:1080'
```

### Quality Management

```bash
# Remove lower quality files (MP3 128kbit) when higher quality exists (MP4/AAC >=96kbit)
audiothek --remove-lower-quality --folder '/path/to/archive'

# Preview what would be removed without making changes
audiothek --remove-lower-quality --dry-run --folder '/path/to/archive'
```

### GraphQL Response Caching

The downloader caches GraphQL responses in a small SQLite database to minimize duplicate API calls and speed up repeated downloads.

- **Default location**: `$XDG_CACHE_HOME/audiothek-downloader` or `~/.cache/audiothek-downloader`
- **CLI override**: `--cache-dir /path/to/cache`
- **TTL**: Entries are reused for up to 6 hours
- **Disable caching**: Set `AUDIOTHEK_DISABLE_CACHE=1` (or `true`, `yes`) before running the CLI

Example:

```bash
# Store cache inside the project directory
audiothek --url 'https://www.ardaudiothek.de/sendung/example/12345678/' --cache-dir './.cache/audiothek'

# Temporarily disable caching
AUDIOTHEK_DISABLE_CACHE=1 audiothek --id 'urn:ard:episode:1234567890abcdef'
```

### Parallel Download Workers

Episode downloads run concurrently to improve throughput. Control the concurrency with `--max-workers` (default: `4`, max `16`):

```bash
# Use 8 worker threads for faster downloads on fast connections
audiothek --url 'https://www.ardaudiothek.de/sendung/example/12345678/' --max-workers 8
```

Using more workers increases CPU/network usage. If you encounter rate limits or run on low-powered hardware, reduce the value (minimum `1`).

## Python Library Usage

```python
from audiothek import AudiothekDownloader, AudiothekClient

# Create downloader instance
downloader = AudiothekDownloader(base_folder="/path/to/output", proxy=None)

# Download content by URL
downloader.download_from_url("https://www.ardaudiothek.de/sendung/example/12345678/")

# Download content by ID
downloader.download_from_id("urn:ard:episode:1234567890abcdef")

# Update existing downloads
downloader.update_all_folders()

# Remove lower quality duplicates
downloader.remove_lower_quality_files(dry_run=True)

# Use the client directly for API operations
client = AudiothekClient()
program_sets = client.find_program_sets_by_editorial_category_id("category123")
```

## Output Structure

```
output/
  <program_id> <program_title>/
    <slug>_<episode_id>.mp3/.mp4/.m4a/.aac  # Audio file with appropriate extension
    <slug>_<episode_id>.jpg                 # 16:9 cover image
    <slug>_<episode_id>_x1.jpg              # 1:1 cover image
    <slug>_<episode_id>.json                # Episode metadata
    <program_id>.json                       # Program metadata
    <program_id>.jpg                        # Program cover image
```

## Development

### Running Tests

```bash
# Run the test suite
uv run make test

# Run specific validation tools
uv run make validate
```

### Code Quality Tools

The project uses several code quality tools:
- `ruff` for linting and formatting
- `pytest` with high coverage requirements
- `pyright` for type checking
- `bandit` for security analysis
- `vulture` for dead code detection
- `radon`/`xenon` for complexity analysis

## Notes & Limitations

- Only episodes with accessible `downloadUrl` or streaming `url` can be downloaded
- DRM-protected content may not be downloadable
- Please respect ARD Audiothek's terms of service
- API changes by ARD may require updates to the GraphQL queries in `src/audiothek/graphql/`

## License

This project is licensed under the Mozilla Public License Version 2.0 - see the [LICENSE](LICENSE) file for details.
