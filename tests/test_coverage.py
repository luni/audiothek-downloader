"""Additional tests to improve coverage to 85%."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
import requests

from audiothek import AudiothekClient, AudiothekDownloader
from tests.conftest import MockResponse


def test_find_program_sets_by_editorial_category_id_pagination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test pagination in find_program_sets_by_editorial_category_id."""
    client = AudiothekClient()

    calls = []

    def _mock_graphql_get(self, query, variables):
        calls.append(variables)
        if variables["offset"] == 0:
            return {
                "data": {
                    "result": {
                        "nodes": [{"id": "ps1"}, {"id": "ps2"}],
                        "pageInfo": {"hasNextPage": True}
                    }
                }
            }
        else:
            return {
                "data": {
                    "result": {
                        "nodes": [{"id": "ps3"}],
                        "pageInfo": {"hasNextPage": False}
                    }
                }
            }

    monkeypatch.setattr(AudiothekClient, "_graphql_get", _mock_graphql_get)

    result = client.find_program_sets_by_editorial_category_id("ec123", limit=10)

    assert len(result) == 3
    assert len(calls) == 2
    assert calls[0]["offset"] == 0
    assert calls[1]["offset"] == 24


def test_find_editorial_collections_by_editorial_category_id_breaks_on_no_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test find_editorial_collections_by_editorial_category_id breaks when no sections."""
    client = AudiothekClient()

    def _mock_graphql_get(self, query, variables):
        return {
            "data": {
                "result": {
                    "sections": []  # Empty sections should break the loop
                }
            }
        }

    monkeypatch.setattr(AudiothekClient, "_graphql_get", _mock_graphql_get)

    result = client.find_editorial_collections_by_editorial_category_id("ec123")

    assert result == []


def test_find_editorial_collections_by_editorial_category_id_breaks_on_no_new_collections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test find_editorial_collections_by_editorial_category_id breaks when no new collections."""
    client = AudiothekClient()

    call_count = 0

    def _mock_graphql_get(self, query, variables):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "data": {
                    "result": {
                        "sections": [{
                            "nodes": [{"id": "col1"}]
                        }]
                    }
                }
            }
        else:
            # Second call returns same data, so no new collections
            return {
                "data": {
                    "result": {
                        "sections": [{
                            "nodes": [{"id": "col1"}]  # Same collection
                        }]
                    }
                }
            }

    monkeypatch.setattr(AudiothekClient, "_graphql_get", _mock_graphql_get)

    result = client.find_editorial_collections_by_editorial_category_id("ec123")

    assert len(result) == 1
    assert call_count == 2  # Should make second call and then break


def test_update_all_folders_nonexistent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test update_all_folders with nonexistent directory."""
    nonexistent_dir = str(tmp_path / "nonexistent")

    with caplog.at_level("ERROR"):
        downloader = AudiothekDownloader()
        downloader.update_all_folders(nonexistent_dir)

    assert any("Output directory" in r.message and "does not exist" in r.message for r in caplog.records)


def test_migrate_folders_nonexistent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test migrate_folders with nonexistent directory."""
    nonexistent_dir = str(tmp_path / "nonexistent")

    with caplog.at_level("ERROR"):
        downloader = AudiothekDownloader()
        downloader.migrate_folders(nonexistent_dir)

    assert any("Output directory" in r.message and "does not exist" in r.message for r in caplog.records)


def test_get_program_title_episode_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _get_program_title with episode resource type."""
    downloader = AudiothekDownloader()

    def _mock_get_episode_title(resource_id):
        return "Episode Title"

    monkeypatch.setattr(downloader.client, "get_episode_title", _mock_get_episode_title)

    result = downloader._get_program_title("ep123", "episode")
    assert result == "Episode Title"


def test_get_program_title_program_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _get_program_title with program resource type."""
    downloader = AudiothekDownloader()

    def _mock_get_program_set_title(resource_id):
        return "Program Title"

    monkeypatch.setattr(downloader.client, "get_program_set_title", _mock_get_program_set_title)

    result = downloader._get_program_title("ps123", "program")
    assert result == "Program Title"


def test_get_program_title_collection_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _get_program_title with collection resource type."""
    downloader = AudiothekDownloader()

    def _mock_get_program_set_title(resource_id):
        return "Collection Title"

    monkeypatch.setattr(downloader.client, "get_program_set_title", _mock_get_program_set_title)

    result = downloader._get_program_title("col123", "collection")
    assert result == "Collection Title"


def test_save_collection_data_error_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test _save_collection_data error handling."""
    downloader = AudiothekDownloader()
    collection_data = {"id": "test_ec", "title": "Test Collection"}

    # Mock json.dump to raise an exception
    def _mock_json_dump(*args, **kwargs):
        raise ValueError("JSON error")

    monkeypatch.setattr("json.dump", _mock_json_dump)

    with caplog.at_level("ERROR"):
        downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=True)

    assert any("Error saving editorial collection data" in r.message for r in caplog.records)


def test_save_collection_data_program_set_error_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test _save_collection_data error handling for program sets."""
    downloader = AudiothekDownloader()
    collection_data = {"id": "test_ps", "title": "Test Program Set"}

    # Mock json.dump to raise an exception
    def _mock_json_dump(*args, **kwargs):
        raise ValueError("JSON error")

    monkeypatch.setattr("json.dump", _mock_json_dump)

    with caplog.at_level("ERROR"):
        downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=False)

    assert any("Error saving program set data" in r.message for r in caplog.records)
