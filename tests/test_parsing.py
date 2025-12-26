"""Tests for URL and ID parsing functionality."""

import pytest
from audiothek import AudiothekClient, ResourceInfo


def test_parse_url_episode_urn() -> None:
    assert AudiothekClient.parse_url("https://www.ardaudiothek.de/folge/x/urn:ard:episode:abc/") == ResourceInfo(resource_type="episode", resource_id="urn:ard:episode:abc")


def test_parse_url_collection_urn() -> None:
    assert AudiothekClient.parse_url("https://www.ardaudiothek.de/sammlung/x/urn:ard:page:xyz") == ResourceInfo(resource_type="collection", resource_id="urn:ard:page:xyz")


def test_parse_url_program_urn_and_numeric() -> None:
    assert AudiothekClient.parse_url("https://www.ardaudiothek.de/sendung/x/urn:ard:show:111") == ResourceInfo(resource_type="program", resource_id="urn:ard:show:111")
    assert AudiothekClient.parse_url("https://www.ardaudiothek.de/sendung/x/12345/") == ResourceInfo(resource_type="program", resource_id="12345")


def test_parse_url_none() -> None:
    assert AudiothekClient.parse_url("https://www.ardaudiothek.de/sendung/x/") is None


def test_parse_url_fallback_urn() -> None:
    # Test fallback for other urn types
    assert AudiothekClient.parse_url("https://www.ardaudiothek.de/x/urn:ard:other:abc/") == ResourceInfo(resource_type="program", resource_id="urn:ard:other:abc")


def test_determine_resource_type_from_id_episode() -> None:
    assert AudiothekClient.determine_resource_type_from_id("urn:ard:episode:abc") == ResourceInfo(resource_type="episode", resource_id="urn:ard:episode:abc")


def test_determine_resource_type_from_id_collection() -> None:
    assert AudiothekClient.determine_resource_type_from_id("urn:ard:page:xyz") == ResourceInfo(resource_type="collection", resource_id="urn:ard:page:xyz")


def test_determine_resource_type_from_id_program() -> None:
    assert AudiothekClient.determine_resource_type_from_id("urn:ard:show:111") == ResourceInfo(resource_type="program", resource_id="urn:ard:show:111")
    assert AudiothekClient.determine_resource_type_from_id("urn:ard:other:123") == ResourceInfo(resource_type="program", resource_id="urn:ard:other:123")


def test_determine_resource_type_from_id_numeric() -> None:
    assert AudiothekClient.determine_resource_type_from_id("12345") == ResourceInfo(resource_type="program", resource_id="12345")


def test_determine_resource_type_from_id_alphanumeric() -> None:
    assert AudiothekClient.determine_resource_type_from_id("ps1") == ResourceInfo(resource_type="program", resource_id="ps1")
    assert AudiothekClient.determine_resource_type_from_id("abc123") == ResourceInfo(resource_type="program", resource_id="abc123")


def test_determine_resource_type_from_id_none() -> None:
    assert AudiothekClient.determine_resource_type_from_id("invalid_id") is None
