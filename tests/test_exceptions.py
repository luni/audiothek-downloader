"""Tests for custom exceptions."""

import pytest

from audiothek.exceptions import (
    AudiothekError,
    ResourceNotFoundError,
    ResourceParseError,
    DownloadError,
    FileOperationError,
    GraphQLError,
)


class TestAudiothekError:
    """Test cases for the base AudiothekError exception."""

    def test_base_exception_can_be_raised(self) -> None:
        """Test that the base exception can be raised and caught."""
        with pytest.raises(AudiothekError):
            raise AudiothekError("Test error")


class TestResourceNotFoundError:
    """Test cases for ResourceNotFoundError."""

    def test_resource_not_found_error_without_type(self) -> None:
        """Test ResourceNotFoundError without resource type."""
        error = ResourceNotFoundError("12345")
        assert error.resource_id == "12345"
        assert error.resource_type is None
        assert str(error) == "Resource not found: 12345"

    def test_resource_not_found_error_with_type(self) -> None:
        """Test ResourceNotFoundError with resource type."""
        error = ResourceNotFoundError("12345", "episode")
        assert error.resource_id == "12345"
        assert error.resource_type == "episode"
        assert str(error) == "Episode not found: 12345"

    def test_resource_not_found_error_with_different_types(self) -> None:
        """Test ResourceNotFoundError with different resource types."""
        error1 = ResourceNotFoundError("67890", "program")
        assert str(error1) == "Program not found: 67890"

        error2 = ResourceNotFoundError("abc123", "collection")
        assert str(error2) == "Collection not found: abc123"

        error3 = ResourceNotFoundError("xyz789", "show")
        assert str(error3) == "Show not found: xyz789"

    def test_resource_not_found_error_inheritance(self) -> None:
        """Test that ResourceNotFoundError inherits from AudiothekError."""
        error = ResourceNotFoundError("12345")
        assert isinstance(error, AudiothekError)


class TestResourceParseError:
    """Test cases for ResourceParseError."""

    def test_resource_parse_error_without_message(self) -> None:
        """Test ResourceParseError without additional message."""
        error = ResourceParseError("invalid_url")
        assert error.url_or_id == "invalid_url"
        assert str(error) == "Could not parse resource: invalid_url"

    def test_resource_parse_error_with_message(self) -> None:
        """Test ResourceParseError with additional message."""
        error = ResourceParseError("invalid_url", "Invalid format")
        assert error.url_or_id == "invalid_url"
        assert str(error) == "Could not parse resource: invalid_url - Invalid format"

    def test_resource_parse_error_with_id(self) -> None:
        """Test ResourceParseError with ID instead of URL."""
        error = ResourceParseError("invalid_id", "ID not found")
        assert error.url_or_id == "invalid_id"
        assert str(error) == "Could not parse resource: invalid_id - ID not found"

    def test_resource_parse_error_inheritance(self) -> None:
        """Test that ResourceParseError inherits from AudiothekError."""
        error = ResourceParseError("test_url")
        assert isinstance(error, AudiothekError)


class TestDownloadError:
    """Test cases for DownloadError."""

    def test_download_error_without_status_and_message(self) -> None:
        """Test DownloadError without status code and message."""
        error = DownloadError("http://example.com/audio.mp3")
        assert error.url == "http://example.com/audio.mp3"
        assert error.status_code is None
        assert str(error) == "Failed to download: http://example.com/audio.mp3"

    def test_download_error_with_status_code(self) -> None:
        """Test DownloadError with status code."""
        error = DownloadError("http://example.com/audio.mp3", 404)
        assert error.url == "http://example.com/audio.mp3"
        assert error.status_code == 404
        assert str(error) == "Failed to download: http://example.com/audio.mp3 (Status: 404)"

    def test_download_error_with_message(self) -> None:
        """Test DownloadError with message but no status code."""
        error = DownloadError("http://example.com/audio.mp3", message="Connection timeout")
        assert error.url == "http://example.com/audio.mp3"
        assert error.status_code is None
        assert str(error) == "Failed to download: http://example.com/audio.mp3 - Connection timeout"

    def test_download_error_with_status_and_message(self) -> None:
        """Test DownloadError with both status code and message."""
        error = DownloadError("http://example.com/audio.mp3", 500, "Server error")
        assert error.url == "http://example.com/audio.mp3"
        assert error.status_code == 500
        assert str(error) == "Failed to download: http://example.com/audio.mp3 (Status: 500) - Server error"

    def test_download_error_different_status_codes(self) -> None:
        """Test DownloadError with different status codes."""
        test_cases = [
            (200, "Success"),
            (403, "Forbidden"),
            (404, "Not Found"),
            (500, "Internal Server Error"),
            (503, "Service Unavailable"),
        ]

        for status_code, _ in test_cases:
            error = DownloadError("http://example.com/test.mp3", status_code)
            assert error.status_code == status_code
            assert f"(Status: {status_code})" in str(error)

    def test_download_error_inheritance(self) -> None:
        """Test that DownloadError inherits from AudiothekError."""
        error = DownloadError("http://example.com/test.mp3")
        assert isinstance(error, AudiothekError)


class TestFileOperationError:
    """Test cases for FileOperationError."""

    def test_file_operation_error_without_message(self) -> None:
        """Test FileOperationError without additional message."""
        error = FileOperationError("/path/to/file.txt", "read")
        assert error.file_path == "/path/to/file.txt"
        assert error.operation == "read"
        assert str(error) == "Failed to read file: /path/to/file.txt"

    def test_file_operation_error_with_message(self) -> None:
        """Test FileOperationError with additional message."""
        error = FileOperationError("/path/to/file.txt", "write", "Permission denied")
        assert error.file_path == "/path/to/file.txt"
        assert error.operation == "write"
        assert str(error) == "Failed to write file: /path/to/file.txt - Permission denied"

    def test_file_operation_error_different_operations(self) -> None:
        """Test FileOperationError with different operations."""
        test_cases = [
            ("create", "Failed to create file: /path/to/file.txt"),
            ("delete", "Failed to delete file: /path/to/file.txt"),
            ("move", "Failed to move file: /path/to/file.txt"),
            ("copy", "Failed to copy file: /path/to/file.txt"),
        ]

        for operation, expected_message in test_cases:
            error = FileOperationError("/path/to/file.txt", operation)
            assert str(error) == expected_message

    def test_file_operation_error_inheritance(self) -> None:
        """Test that FileOperationError inherits from AudiothekError."""
        error = FileOperationError("/path/to/file.txt", "read")
        assert isinstance(error, AudiothekError)


class TestGraphQLError:
    """Test cases for GraphQLError."""

    def test_graphql_error_without_variables_and_message(self) -> None:
        """Test GraphQLError without variables and message."""
        error = GraphQLError("getProgram")
        assert error.query_name == "getProgram"
        assert error.variables is None
        assert str(error) == "GraphQL query failed: getProgram"

    def test_graphql_error_with_variables(self) -> None:
        """Test GraphQLError with variables."""
        variables = {"id": "12345", "limit": 10}
        error = GraphQLError("getProgram", variables)
        assert error.query_name == "getProgram"
        assert error.variables == variables
        assert str(error) == "GraphQL query failed: getProgram"

    def test_graphql_error_with_message(self) -> None:
        """Test GraphQLError with message."""
        error = GraphQLError("getProgram", message="Invalid query syntax")
        assert error.query_name == "getProgram"
        assert error.variables is None
        assert str(error) == "GraphQL query failed: getProgram - Invalid query syntax"

    def test_graphql_error_with_variables_and_message(self) -> None:
        """Test GraphQLError with both variables and message."""
        variables = {"id": "12345"}
        error = GraphQLError("getProgram", variables, "Network timeout")
        assert error.query_name == "getProgram"
        assert error.variables == variables
        assert str(error) == "GraphQL query failed: getProgram - Network timeout"

    def test_graphql_error_different_query_names(self) -> None:
        """Test GraphQLError with different query names."""
        test_cases = [
            "getEpisode",
            "getCollection",
            "searchPrograms",
            "getProgramSet",
        ]

        for query_name in test_cases:
            error = GraphQLError(query_name)
            assert error.query_name == query_name
            assert str(error) == f"GraphQL query failed: {query_name}"

    def test_graphql_error_complex_variables(self) -> None:
        """Test GraphQLError with complex variables structure."""
        variables = {
            "filter": {"programSetId": "123", "limit": 20},
            "sort": {"field": "publishDate", "order": "desc"},
        }
        error = GraphQLError("searchEpisodes", variables)
        assert error.variables == variables

    def test_graphql_error_inheritance(self) -> None:
        """Test that GraphQLError inherits from AudiothekError."""
        error = GraphQLError("getProgram")
        assert isinstance(error, AudiothekError)


class TestExceptionChaining:
    """Test exception chaining and behavior."""

    def test_exception_can_be_caught_as_base_type(self) -> None:
        """Test that all custom exceptions can be caught as AudiothekError."""
        exceptions = [
            ResourceNotFoundError("123"),
            ResourceParseError("url"),
            DownloadError("http://example.com"),
            FileOperationError("/path/file.txt", "read"),
            GraphQLError("query"),
        ]

        for exc in exceptions:
            with pytest.raises(AudiothekError):
                raise exc

    def test_exception_attributes_are_accessible(self) -> None:
        """Test that exception attributes are accessible after raising."""
        try:
            raise ResourceNotFoundError("12345", "episode")
        except ResourceNotFoundError as e:
            assert e.resource_id == "12345"
            assert e.resource_type == "episode"
            assert "Episode not found" in str(e)
