import argparse
import json
import logging
import os
import re
from typing import Any

import requests

REQUEST_TIMEOUT = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]%(message)s")


def main(url: str, folder: str, id: str = "") -> None:
    """Parse URL and download episodes from ARD Audiothek.

    Args:
        url: The URL of the ARD Audiothek show or collection
        folder: The output directory to save downloaded files
        id: The direct ID of the resource (alternative to URL)

    Returns:
        None

    """
    if id:
        resource = determine_resource_type_from_id(id)
        if not resource:
            logging.error("Could not determine resource type from ID.")
            return
        resource_type, resource_id = resource
        if resource_type == "episode":
            download_single_episode(resource_id, folder)
        else:
            download_collection("", resource_id, folder, resource_type == "collection")
    else:
        resource = parse_url(url)
        if not resource:
            logging.error("Could not determine resource ID from URL.")
            return

        resource_type, resource_id = resource
        if resource_type == "episode":
            download_single_episode(resource_id, folder)
        else:
            download_collection(url, resource_id, folder, resource_type == "collection")


def determine_resource_type_from_id(id: str) -> tuple[str, str] | None:
    """Determine resource type from ID pattern.

    Args:
        id: The ID to analyze

    Returns:
        A tuple of (resource_type, id) where resource_type is one of 'episode', 'collection', or 'program'

    """
    if id.startswith("urn:ard:episode:"):
        return "episode", id
    if id.startswith("urn:ard:page:"):
        return "collection", id
    if id.startswith("urn:ard:show:"):
        return "program", id
    # fallback: treat other urns as program sets
    if id.startswith("urn:ard:"):
        return "program", id
    # numeric IDs are typically programs
    if id.isdigit():
        return "program", id
    # alphanumeric IDs (like "ps1") are also treated as programs
    if re.match(r"^[a-zA-Z0-9]+$", id):
        return "program", id
    return None


def parse_url(url: str) -> tuple[str, str] | None:
    """Parse Audiothek URL and return (resource_type, id).

    Args:
        url: The URL to parse

    Returns:
        A tuple of (resource_type, id) where resource_type is one of 'episode', 'collection', or 'program'

    """
    urn_match = re.search(r"/(urn:ard:[^/]+)/?$", url)
    if urn_match:
        urn = urn_match.group(1)
        if urn.startswith("urn:ard:episode:"):
            return "episode", urn
        if urn.startswith("urn:ard:page:"):
            return "collection", urn
        if urn.startswith("urn:ard:show:"):
            return "program", urn
        # fallback: treat other urns as program sets
        return "program", urn

    numeric_match = re.search(r"/(\d+)/?$", url)
    if numeric_match:
        return "program", numeric_match.group(1)

    return None


def download_single_episode(episode_id: str, folder: str) -> None:
    """Fetch and store a single episode.

    Args:
        episode_id: The ID of the episode to download
        folder: The output directory to save the downloaded file

    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    graphql_dir = os.path.join(base_dir, "graphql")
    query_path = os.path.join(graphql_dir, "EpisodeQuery.graphql")
    with open(query_path) as f:
        query = f.read()

    response = requests.get(
        "https://api.ardaudiothek.de/graphql",
        params={"query": query, "variables": json.dumps({"id": episode_id})},
        timeout=REQUEST_TIMEOUT,
    )
    response_json = response.json()

    node = response_json.get("data", {}).get("result")
    if not node:
        logging.error("Episode not found for %s", episode_id)
        return

    save_nodes([node], folder)


def download_collection(url: str, id: str, folder: str, is_editorial_collection: bool) -> None:
    """Download episodes from ARD Audiothek.

    Args:
        url: The URL of the ARD Audiothek show or collection
        id: The program set ID extracted from the URL
        folder: The output directory to save downloaded files
        is_editorial_collection: Whether the URL points to an editorial collection

    Returns:
        None

    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    graphql_dir = os.path.join(base_dir, "graphql")

    query_file = "editorialCollection.graphql" if is_editorial_collection else "ProgramSetEpisodesQuery.graphql"
    query_path = os.path.join(graphql_dir, query_file)
    with open(query_path) as f:
        query = f.read()

    nodes: list[dict] = []
    offset = 0
    count = 24
    while True:
        variables = {"id": id, "offset": offset, "count": count}
        response = requests.get(
            "https://api.ardaudiothek.de/graphql",
            params={"query": query, "variables": json.dumps(variables)},
            timeout=REQUEST_TIMEOUT,
        )
        response_json = response.json()

        results = response_json.get("data", {}).get("result", {})
        if not results:
            break

        items = results.get("items", {}) or {}
        page_nodes = items.get("nodes", []) or []
        if isinstance(page_nodes, list):
            nodes.extend(page_nodes)

        page_info = items.get("pageInfo", {}) or {}
        if not page_info.get("hasNextPage"):
            break
        offset += count

    save_nodes(nodes, folder)


def save_nodes(nodes: list[dict[str, Any]], folder: str) -> None:
    """Write episode assets (cover, audio, metadata) to disk."""
    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or index)
        title = node.get("title") or node_id

        # get title from infos
        array_filename = re.findall(r"(\w+)", title)
        filename_base = "_".join(array_filename) if array_filename else node_id
        filename = f"{filename_base}_{node_id}"

        image = node.get("image") or {}
        image_url_template = image.get("url") or ""
        image_url = image_url_template.replace("{width}", "2000") if image_url_template else ""
        image_url_x1_template = image.get("url1X1") or ""
        image_url_x1 = image_url_x1_template.replace("{width}", "2000") if image_url_x1_template else ""

        audios = node.get("audios") or []
        first_audio = audios[0] if audios and isinstance(audios[0], dict) else None
        mp3_url = ""
        if first_audio:
            mp3_url = first_audio.get("downloadUrl") or first_audio.get("url") or ""
        if not mp3_url:
            continue

        program_set = node.get("programSet") or {}
        programset_id = program_set.get("id") or "episode"

        program_path: str = os.path.join(folder, programset_id)

        # get information of program
        try:
            os.makedirs(program_path, exist_ok=True)
        except Exception as e:
            logging.error("[Error] Couldn't create output directory!")
            logging.exception(e)
            return

        # write images
        image_file_path = os.path.join(program_path, filename + ".jpg")
        image_file_x1_path = os.path.join(program_path, filename + "_x1.jpg")

        if image_url and not os.path.exists(image_file_path):
            response_image = requests.get(image_url, timeout=REQUEST_TIMEOUT)
            with open(image_file_path, "wb") as f:
                f.write(response_image.content)

        if image_url_x1 and not os.path.exists(image_file_x1_path):
            response_image = requests.get(image_url_x1, timeout=REQUEST_TIMEOUT)
            with open(image_file_x1_path, "wb") as f:
                f.write(response_image.content)

        # write mp3
        mp3_file_path = os.path.join(program_path, filename + ".mp3")

        logging.info("Download: %s of %s -> %s", index + 1, len(nodes), mp3_file_path)
        if not os.path.exists(mp3_file_path):
            response_mp3 = requests.get(mp3_url, timeout=REQUEST_TIMEOUT)
            with open(mp3_file_path, "wb") as f:
                f.write(response_mp3.content)

        # write meta
        meta_file_path = os.path.join(program_path, filename + ".json")
        data = {
            "id": node_id,
            "title": title,
            "description": node.get("description"),
            "summary": node.get("summary"),
            "duration": node.get("duration"),
            "publishDate": node.get("publishDate"),
            "programSet": {
                "id": programset_id,
                "title": program_set.get("title"),
                "path": program_set.get("path"),
            },
        }

        with open(meta_file_path, "w") as f:
            json.dump(data, f, indent=4)


if __name__ == "__main__":
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
    parser.add_argument("--folder", "-f", type=str, default="./output", help="Folder to save all mp3s")

    args = parser.parse_args()
    url = args.url
    id = args.id
    folder = os.path.realpath(args.folder)
    main(url, folder, id)
