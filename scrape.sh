#!/bin/bash
if [ "$1" != "" ]; then
    uv run python3 audiothek-downloader/audiothek.py --url "https://www.ardaudiothek.de/sendung/100-aus-100-die-hoerspiel-collection$1/"
    exit
fi

find output -mindepth 1 -maxdepth 1  | grep -o -E '\/[0-9]+$' | while read id; do
    echo "$id";
    uv run python3 audiothek-downloader/audiothek.py --url "https://www.ardaudiothek.de/sendung/100-aus-100-die-hoerspiel-collection${id}/"
done
