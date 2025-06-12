import argparse
import json
import logging
import os
import re
import sys

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]%(message)s")


def main(url: str, folder: str) -> None:
    match = re.search(r"/(\d+)/?$", url)
    if match:
        id = match.group(1)
        downloadEpisodes(id, folder)


def downloadEpisodes(id: str, folder: str) -> None:
    query = open(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "graphql",
            "ProgramSetEpisodesQuery.graphql",
        )
    ).read()

    # change query if url is "sammlung"
    if "sammlung" in url.lower():
        query = open(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "graphql",
                "editorialCollection.graphql",
            )
        ).read()

    variables = {"id": id}
    response = requests.get(
        "https://api.ardaudiothek.de/graphql",
        params={"query": query, "variables": json.dumps(variables)},
    )
    response_json = response.json()

    results = response_json.get("data", {}).get("result", {})
    nodes = []
    if results:
        nodes = results.get("items", {}).get("nodes", {})

    for index, node in enumerate(nodes):
        number = node["id"]

        id = node.get("id")
        title = node.get("title")

        # get title from infos
        array_filename = re.findall(r"(\w+)", title)
        if len(array_filename) > 0:
            filename = "_".join(array_filename)
        else:
            filename = id

        filename = filename + "_" + str(number)

        # get image information
        image_url = node.get("image").get("url")
        image_url = image_url.replace("{width}", "2000")
        image_url_x1 = node.get("image").get("url1X1")
        image_url_x1 = image_url_x1.replace("{width}", "2000")
        if not node.get("audios"):
            continue
        mp3_url = node.get("audios")[0].get("downloadUrl") or node.get("audios")[0].get("url")
        programset_id = node.get("programSet").get("id")

        program_path: str = os.path.join(folder, programset_id)

        # get information of program
        if programset_id:
            try:
                os.makedirs(program_path)
            except FileExistsError:
                pass
            except Exception as e:
                logging.error("[Error] Couldn't create output directory!")
                logging.exception(e)
                return

            # write images
            image_file_path = os.path.join(program_path, filename + ".jpg")
            image_file_x1_path = os.path.join(program_path, filename + "_x1.jpg")

            if not os.path.exists(image_file_path) or not os.path.exists(image_file_x1_path):
                response_image = requests.get(image_url)
                with open(image_file_path, "wb") as f:
                    f.write(response_image.content)

            if not os.path.exists(image_file_x1_path):
                response_image = requests.get(image_url_x1)
                with open(image_file_x1_path, "wb") as f:
                    f.write(response_image.content)

            # write mp3
            mp3_file_path = os.path.join(program_path, filename + ".mp3")

            logging.info("Download: %s of %s -> %s", index + 1, len(nodes), mp3_file_path)
            if os.path.exists(mp3_file_path) == False and mp3_url:
                response_mp3 = requests.get(mp3_url)
                with open(mp3_file_path, "wb") as f:
                    f.write(response_mp3.content)

            # write meta
            meta_file_path = os.path.join(program_path, filename + ".json")
            data = {
                "id": id,
                "title": title,
                "description": node.get("description"),
                "summary": node.get("summary"),
                "duration": node.get("duration"),
                "publishDate": node.get("publishDate"),
                "programSet": {
                    "id": programset_id,
                    "title": node.get("programSet").get("title"),
                    "path": node.get("programSet").get("path"),
                },
            }

            with open(meta_file_path, "w") as f:
                json.dump(data, f, indent=4)
        else:
            logging.error("No programset_id found!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARD Audiothek downloader.")
    parser.add_argument(
        "--url",
        "-u",
        type=str,
        default="",
        required=True,
        help="Insert audiothek url (e.g. https://www.ardaudiothek.de/sendung/2035-die-zukunft-beginnt-jetzt-scifi-mit-niklas-kolorz/12121989/)",
    )
    parser.add_argument("--folder", "-f", type=str, default="./output", help="Folder to save all mp3s")

    args = parser.parse_args()
    url = args.url
    folder = os.path.realpath(args.folder)
    main(url, folder)
