import argparse
import logging
import os

from audiothek import AudiothekDownloader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]%(message)s")


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
        "--search-type",
        choices=["program-sets", "collections", "all"],
        default="all",
        help="When using --editorial-category-id, select what to return",
    )

    args = parser.parse_args()
    url = args.url
    id = args.id
    update_folders = args.update_folders
    migrate_folders = args.migrate_folders
    editorial_category_id = args.editorial_category_id
    search_type = args.search_type
    folder = os.path.realpath(args.folder)

    _process_request(url, folder, id, update_folders, migrate_folders, editorial_category_id, search_type)


def _process_request(
    url: str,
    folder: str,
    id: str = "",
    update_folders: bool = False,
    migrate_folders: bool = False,
    editorial_category_id: str = "",
    search_type: str = "all",
) -> None:
    """Parse URL and download episodes from ARD Audiothek.

    Args:
        url: The URL of the ARD Audiothek show or collection
        folder: The output directory to save downloaded files
        id: The direct ID of the resource (alternative to URL)
        update_folders: Whether to update all existing subfolders
        migrate_folders: Whether to migrate folders to new naming schema
        editorial_category_id: The editorial category ID to search for program sets and/or editorial collections
        search_type: Whether to search for program sets, editorial collections, or both

    Returns:
        None

    """
    downloader = AudiothekDownloader(folder)

    if migrate_folders:
        downloader.migrate_folders(folder)
        return

    if update_folders:
        downloader.update_all_folders(folder)
        return

    if editorial_category_id:
        if search_type in {"program-sets", "all"}:
            program_sets = downloader.find_program_sets_by_editorial_category_id(editorial_category_id)
            for program_set in program_sets:
                print(program_set)

        if search_type in {"collections", "all"}:
            collections = downloader.find_editorial_collections_by_editorial_category_id(editorial_category_id)
            for collection in collections:
                print(collection)
        return

    if id:
        downloader.download_from_id(id, folder)
    else:
        downloader.download_from_url(url, folder)


if __name__ == "__main__":
    main()
