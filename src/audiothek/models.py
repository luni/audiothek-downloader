"""Data models for the audiothek-downloader."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ImageMetadata:
    """Metadata for saving images and files."""

    node_id: str
    title: str
    filename: str
    program_path: str
    program_set: dict[str, Any]
    image_urls: dict[str, str]


@dataclass
class AudioInfo:
    """Information about an audio file."""

    url: str
    download_url: str | None = None
    content_type: str | None = None
    bitrate: int | None = None
    size: int | None = None
    duration: int | None = None


@dataclass
class EpisodeMetadata:
    """Metadata for an episode."""

    id: str
    title: str
    description: str | None = None
    summary: str | None = None
    duration: int | None = None
    publish_date: str | None = None
    program_set_id: str | None = None
    program_set_title: str | None = None
    program_set_path: str | None = None
    audio_urls: list[str] | None = None
    image_url: str | None = None
    image_url_x1: str | None = None

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.audio_urls is None:
            self.audio_urls = []


@dataclass
class ProgramSetMetadata:
    """Metadata for a program set."""

    id: str
    title: str
    core_id: str | None = None
    synopsis: str | None = None
    summary: str | None = None
    editorial_description: str | None = None
    image_url: str | None = None
    sharing_url: str | None = None
    path: str | None = None
    number_of_elements: int | None = None
    broadcast_duration: int | None = None


@dataclass
class ResourceInfo:
    """Information about a resource."""

    resource_type: str
    resource_id: str


@dataclass
class DownloadResult:
    """Result of a download operation."""

    success: bool
    message: str
    file_path: str | None = None
    metadata: dict[str, Any] | None = None
    error: Exception | None = None
