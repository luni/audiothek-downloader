import argparse
import logging
import os
from dataclasses import dataclass

from audiothek import AudiothekDownloader
from audiothek.utils import migrate_folders

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]%(message)s")


@dataclass
class DownloadRequest:
    """Configuration for a download request."""

    url: str = ""
    id: str = ""
    update_folders: bool = False
    migrate_folders_flag: bool = False
    editorial_category_id: str = ""
    search_type: str = "all"
    folder: str = "./output"
    proxy: str | None = None


def main() -> None:
    """Parse command line arguments and download episodes from ARD Audiothek."""
    parser = argparse.ArgumentParser(description="ARD Audiothek downloader.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--url",
        "-u",
        type=str,
        default="",
        help="Insert audiothek url (e.g. https://www.ardaudiothek.de/sendung/kein-mucks-der-krimi-podcast-mit-bastian-pastewka/urn:ard:show:e01e22ff9344b2a4/)",
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
        "--editorial-category-id",
        type=str,
        default="",
        help="Search for program sets and/or editorial collections by editorial category id",
    )
    parser.add_argument("--folder", "-f", type=str, default="./output", help="Folder to save all mp3s")
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

    args = parser.parse_args()

    _process_request(
        DownloadRequest(
            url=args.url,
            id=args.id,
            update_folders=args.update_folders,
            migrate_folders_flag=args.migrate_folders,
            editorial_category_id=args.editorial_category_id,
            search_type=args.search_type,
            folder=os.path.realpath(args.folder),
            proxy=args.proxy,
        )
    )


def _process_request(request: DownloadRequest) -> None:
    """Parse URL and download episodes from ARD Audiothek.

    Args:
        request: The download request configuration

    Returns:
        None

    """
    downloader = AudiothekDownloader(request.folder, request.proxy)

    if request.migrate_folders_flag:
        migrate_folders(request.folder, downloader, downloader.logger)
        return

    if request.update_folders:
        downloader.update_all_folders(request.folder)
        return

    if request.editorial_category_id:
        if request.search_type in {"program-sets", "all"}:
            program_sets = downloader.find_program_sets_by_editorial_category_id(request.editorial_category_id)
            for program_set in program_sets:
                print(program_set)

        if request.search_type in {"collections", "all"}:
            collections = downloader.find_editorial_collections_by_editorial_category_id(request.editorial_category_id)
            for collection in collections:
                print(collection)
        return

    if request.id:
        downloader.download_from_id(request.id, request.folder)
    else:
        downloader.download_from_url(request.url, request.folder)


if __name__ == "__main__":
    main()
