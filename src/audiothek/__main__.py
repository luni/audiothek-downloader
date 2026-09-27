import argparse
import logging
import os
import sys
from dataclasses import dataclass

from audiothek import AudiothekDownloader
from audiothek.utils import cleanup_files, migrate_folders, rename_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@dataclass
class DownloadRequest:
    """Configuration for a download request."""

    url: str = ""
    id: str = ""
    update_folders: bool = False
    migrate_folders_flag: bool = False
    rename_flag: bool = False
    cleanup_flag: bool = False
    remove_lower_quality: bool = False
    dry_run: bool = False
    editorial_category_id: str = ""
    search_type: str = "all"
    folder: str = "./output"
    proxy: str | None = None
    cache_dir: str | None = None
    max_workers: int = 4


def main() -> int:
    """Parse command line arguments and download episodes from ARD Audiothek.

    Returns:
        0 on success, 1 on failure

    """
    parser = argparse.ArgumentParser(description="ARD Audiothek downloader.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--url",
        "-u",
        type=str,
        default="",
        help="Insert audiothek url (e.g. https://www.ardsounds.de/sendung/kein-mucks-der-krimi-podcast-mit-bastian-pastewka/urn:ard:show:e01e22ff9344b2a4/)",
    )
    group.add_argument(
        "--id",
        "-i",
        type=str,
        default="",
        help="Insert audiothek resource ID directly (e.g. urn:ard:episode:123456789 or 123456789)",
    )
    group.add_argument(
        "--update-folders",
        action="store_true",
        help="Update all subfolders in output directory by crawling through existing IDs",
    )
    group.add_argument(
        "--migrate-folders",
        action="store_true",
        help="Migrate existing folders to new naming schema (ID + Title)",
    )
    group.add_argument(
        "--rename",
        action="store_true",
        help="Rename existing files and folders to the current naming scheme so downloads are recognized instead of re-fetched",
    )
    group.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete dead artifacts (stale locks, partial downloads) from the output folder",
    )
    group.add_argument(
        "--remove-lower-quality",
        action="store_true",
        help="Remove lower quality files (MP3 128kbit) when higher quality (MP4/AAC >=96kbit) exists",
    )
    group.add_argument(
        "--editorial-category-id",
        type=str,
        default="",
        help="Search for program sets and/or editorial collections by editorial category id",
    )
    parser.add_argument("--folder", "-f", type=str, default="./output", help="Folder to save all mp3s")
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="Directory for GraphQL response cache (default: ~/.cache/audiothek-downloader)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Maximum number of parallel download workers (default: 4, max 16)",
    )
    parser.add_argument(
        "--proxy",
        "-p",
        type=str,
        default=None,
        help='Proxy URL (e.g. "http://proxy.example.com:8080" or "socks5://proxy.example.com:1080")',
    )
    parser.add_argument(
        "--search-type",
        choices=["program-sets", "collections", "all"],
        default="all",
        help="When using --editorial-category-id, select what to return",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files (use with --remove-lower-quality, --rename, or --cleanup)",
    )

    args = parser.parse_args()

    return _process_request(
        DownloadRequest(
            url=args.url,
            id=args.id,
            update_folders=args.update_folders,
            migrate_folders_flag=args.migrate_folders,
            rename_flag=args.rename,
            cleanup_flag=args.cleanup,
            remove_lower_quality=args.remove_lower_quality,
            dry_run=args.dry_run,
            editorial_category_id=args.editorial_category_id,
            search_type=args.search_type,
            folder=os.path.realpath(args.folder),
            proxy=args.proxy,
            cache_dir=args.cache_dir,
            max_workers=max(1, min(int(args.max_workers), 16)),
        )
    )


def _process_request(request: DownloadRequest) -> int:
    """Parse URL and download episodes from ARD Audiothek.

    Args:
        request: The download request configuration

    Returns:
        0 on success, 1 on failure

    """
    downloader = AudiothekDownloader(
        base_folder=request.folder,
        proxy=request.proxy,
        max_workers=request.max_workers,
        cache_dir=request.cache_dir,
    )

    if request.dry_run and not (request.remove_lower_quality or request.rename_flag or request.cleanup_flag):
        downloader.logger.warning("--dry-run has no effect for this operation; real changes will be made")

    if request.migrate_folders_flag:
        return 0 if migrate_folders(request.folder, downloader, downloader.logger) else 1

    if request.rename_flag:
        return 0 if rename_files(request.folder, downloader.logger, dry_run=request.dry_run) else 1

    if request.cleanup_flag:
        return 0 if cleanup_files(request.folder, downloader.logger, dry_run=request.dry_run) else 1

    if request.update_folders:
        result = downloader.update_all_folders(request.folder)
        return 0 if result is not None and result.success else 1

    if request.remove_lower_quality:
        result = downloader.remove_lower_quality_files(request.folder, dry_run=request.dry_run)
        return 0 if result is not None and result.success else 1

    if request.editorial_category_id:
        try:
            if request.search_type in {"program-sets", "all"}:
                program_sets = downloader.client.find_program_sets_by_editorial_category_id(request.editorial_category_id)
                for program_set in program_sets:
                    print(program_set)

            if request.search_type in {"collections", "all"}:
                collections = downloader.client.find_editorial_collections_by_editorial_category_id(request.editorial_category_id)
                for collection in collections:
                    print(collection)
        except Exception as e:
            downloader.logger.error("Editorial category search failed: %s", e)
            return 1
        return 0

    if request.id:
        result = downloader.download_from_id(request.id, request.folder)
    else:
        result = downloader.download_from_url(request.url, request.folder)

    return 0 if result is not None and result.success else 1


if __name__ == "__main__":
    sys.exit(main())
