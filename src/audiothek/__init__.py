"""ARD Audiothek library for downloading audio content."""

from .client import AudiothekClient
from .downloader import AudiothekDownloader
from .exceptions import (
    AudiothekError,
    DownloadError,
    FileOperationError,
    GraphQLError,
    ResourceNotFoundError,
    ResourceParseError,
)
from .file_utils import (
    FileOperationResult,
    backup_file,
    compare_json_content,
    ensure_directory_exists,
    get_file_size,
    restore_backup,
    safe_write_json,
    set_file_modification_time,
)
from .models import (
    AudioInfo,
    DownloadResult,
    EpisodeMetadata,
    ImageMetadata,
    ProgramSetMetadata,
    ResourceInfo,
)
from .parallel import parallel_download_nodes, parallel_process
from .utils import REQUEST_TIMEOUT, load_graphql_query, sanitize_folder_name

__all__ = [
    # Main classes
    "AudiothekClient",
    "AudiothekDownloader",
    # Exceptions
    "AudiothekError",
    "DownloadError",
    "FileOperationError",
    "GraphQLError",
    "ResourceNotFoundError",
    "ResourceParseError",
    # Models
    "AudioInfo",
    "DownloadResult",
    "EpisodeMetadata",
    "ImageMetadata",
    "ProgramSetMetadata",
    "ResourceInfo",
    # Parallel processing
    "parallel_process",
    "parallel_download_nodes",
    # File utilities
    "FileOperationResult",
    "backup_file",
    "compare_json_content",
    "ensure_directory_exists",
    "get_file_size",
    "restore_backup",
    "safe_write_json",
    "set_file_modification_time",
    # Other utilities
    "REQUEST_TIMEOUT",
    "load_graphql_query",
    "sanitize_folder_name",
]
