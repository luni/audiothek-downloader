"""Tests for URL and ID parsing functionality."""

import pytest
from audiothek import AudiothekDownloader


def test_parse_url_episode_urn() -> None:
    downloader = AudiothekDownloader()
    assert downloader._parse_url("https://www.ardaudiothek.de/folge/x/urn:ard:episode:abc/") == ("episode", "urn:ard:episode:abc")


def test_parse_url_collection_urn() -> None:
    downloader = AudiothekDownloader()
    assert downloader._parse_url("https://www.ardaudiothek.de/sammlung/x/urn:ard:page:xyz") == ("collection", "urn:ard:page:xyz")


def test_parse_url_program_urn_and_numeric() -> None:
    downloader = AudiothekDownloader()
    assert downloader._parse_url("https://www.ardaudiothek.de/sendung/x/urn:ard:show:111") == ("program", "urn:ard:show:111")
    assert downloader._parse_url("https://www.ardaudiothek.de/sendung/x/12345/") == ("program", "12345")


def test_parse_url_none() -> None:
    downloader = AudiothekDownloader()
    assert downloader._parse_url("https://www.ardaudiothek.de/sendung/x/") is None


def test_parse_url_fallback_urn() -> None:
    # Test fallback for other urn types
    downloader = AudiothekDownloader()
    assert downloader._parse_url("https://www.ardaudiothek.de/x/urn:ard:other:abc/") == ("program", "urn:ard:other:abc")


def test_determine_resource_type_from_id_episode() -> None:
    downloader = AudiothekDownloader()
    assert downloader._determine_resource_type_from_id("urn:ard:episode:abc") == ("episode", "urn:ard:episode:abc")


def test_determine_resource_type_from_id_collection() -> None:
    downloader = AudiothekDownloader()
    assert downloader._determine_resource_type_from_id("urn:ard:page:xyz") == ("collection", "urn:ard:page:xyz")


def test_determine_resource_type_from_id_program() -> None:
    downloader = AudiothekDownloader()
    assert downloader._determine_resource_type_from_id("urn:ard:show:111") == ("program", "urn:ard:show:111")
    assert downloader._determine_resource_type_from_id("urn:ard:other:123") == ("program", "urn:ard:other:123")


def test_determine_resource_type_from_id_numeric() -> None:
    downloader = AudiothekDownloader()
    assert downloader._determine_resource_type_from_id("12345") == ("program", "12345")


def test_determine_resource_type_from_id_alphanumeric() -> None:
    downloader = AudiothekDownloader()
    assert downloader._determine_resource_type_from_id("ps1") == ("program", "ps1")
    assert downloader._determine_resource_type_from_id("abc123") == ("program", "abc123")


def test_determine_resource_type_from_id_none() -> None:
    downloader = AudiothekDownloader()
    assert downloader._determine_resource_type_from_id("invalid_id") is None
