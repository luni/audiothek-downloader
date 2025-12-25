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
    parser.add_argument("--folder", "-f", type=str, default="./output", help="Folder to save all mp3s")

    args = parser.parse_args()
    url = args.url
    id = args.id
    update_folders = args.update_folders
    folder = os.path.realpath(args.folder)

    _main(url, folder, id, update_folders)


def _main(url: str, folder: str, id: str = "", update_folders: bool = False) -> None:
    """Parse URL and download episodes from ARD Audiothek.

    Args:
        url: The URL of the ARD Audiothek show or collection
        folder: The output directory to save downloaded files
        id: The direct ID of the resource (alternative to URL)
        update_folders: Whether to update all existing subfolders

    Returns:
        None

    """
    downloader = AudiothekDownloader(folder)

    if update_folders:
        downloader.update_all_folders(folder)
        return

    if id:
        downloader.download_from_id(id, folder)
    else:
        downloader.download_from_url(url, folder)


if __name__ == "__main__":
    main()
