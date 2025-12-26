"""Tests for parallel processing utilities."""

import logging
from unittest.mock import Mock, patch

import pytest

from audiothek.models import DownloadResult
from audiothek.parallel import (
    parallel_process,
    parallel_download_nodes,
    _safe_process_item,
)


class TestParallelProcess:
    """Test cases for parallel_process function."""

    def test_parallel_process_empty_list(self) -> None:
        """Test parallel_process with empty list."""
        result = parallel_process([], lambda x, i, t: x)
        assert result == []

    def test_parallel_process_single_item(self) -> None:
        """Test parallel_process with single item."""
        items = ["test"]
        result = parallel_process(items, lambda x, i, t: f"processed_{x}")
        assert len(result) == 1
        assert result[0][0] is True  # success
        assert result[0][1] == "processed_test"  # result
        assert result[0][2] is None  # exception

    def test_parallel_process_multiple_items(self) -> None:
        """Test parallel_process with multiple items."""
        items = ["item1", "item2", "item3"]

        def process_func(item, index, total):
            return f"{item}_{index}_{total}"

        result = parallel_process(items, process_func)
        assert len(result) == 3

        # All should succeed but order may vary due to parallel processing
        success_count = sum(1 for success, _, _ in result if success)
        assert success_count == 3

        # Check that we got the expected results (order may vary)
        results_dict = {r[1]: True for r in result if r[0]}
        assert "item1_0_3" in results_dict
        assert "item2_1_3" in results_dict
        assert "item3_2_3" in results_dict

    def test_parallel_process_with_exception(self) -> None:
        """Test parallel_process when processing function raises exception."""
        items = ["item1", "item2", "item3"]

        def process_func(item, index, total):
            if item == "item2":
                raise ValueError("Test error")
            return f"processed_{item}"

        result = parallel_process(items, process_func)
        assert len(result) == 3

        # Should have 2 successes and 1 failure
        success_results = [r for r in result if r[0]]
        failed_results = [r for r in result if not r[0]]

        assert len(success_results) == 2
        assert len(failed_results) == 1

        # Check successful results
        success_values = [r[1] for r in success_results]
        assert "processed_item1" in success_values
        assert "processed_item3" in success_values

        # Check failed result
        assert failed_results[0][1] is None
        assert isinstance(failed_results[0][2], ValueError)

    def test_parallel_process_with_custom_logger(self) -> None:
        """Test parallel_process with custom logger."""
        items = ["test"]
        mock_logger = Mock()

        result = parallel_process(items, lambda x, i, t: x, logger=mock_logger)

        # Should have used the provided logger
        assert len(result) == 1
        # Debug message should be logged for successful processing
        mock_logger.debug.assert_called()

    def test_parallel_process_with_different_max_workers(self) -> None:
        """Test parallel_process with different max_workers values."""
        items = ["item1", "item2", "item3"]

        # Test with max_workers=1
        result = parallel_process(items, lambda x, i, t: x, max_workers=1)
        assert len(result) == 3

        # Test with max_workers=10
        result = parallel_process(items, lambda x, i, t: x, max_workers=10)
        assert len(result) == 3

    def test_parallel_process_complex_processing(self) -> None:
        """Test parallel_process with more complex processing logic."""
        items = list(range(5))

        def process_func(item, index, total):
            # Simulate some processing
            result = item * 2 + index
            return {"original": item, "processed": result, "index": index}

        result = parallel_process(items, process_func)
        assert len(result) == 5

        # All should succeed
        success_count = sum(1 for success, _, _ in result if success)
        assert success_count == 5

        # Check that we got the expected results (order may vary)
        processed_items = [r[1] for r in result if r[0]]
        for processed_item in processed_items:
            assert processed_item is not None
            original = processed_item["original"]
            assert processed_item["index"] == original
            assert processed_item["processed"] == original * 2 + original

    @patch('audiothek.parallel.concurrent.futures.ThreadPoolExecutor')
    @patch('audiothek.parallel.concurrent.futures.as_completed')
    def test_parallel_process_executor_exception_handling(self, mock_as_completed: Mock, mock_executor_class: Mock) -> None:
        """Test parallel_process handles exceptions from executor properly."""
        # Mock the executor to raise an exception during future.result()
        mock_future = Mock()
        mock_future.result.side_effect = RuntimeError("Executor error")

        mock_executor = Mock()
        mock_executor.submit.return_value = mock_future
        mock_executor_class.return_value.__enter__.return_value = mock_executor
        mock_executor_class.return_value.__exit__.return_value = None

        # Mock as_completed to return our problematic future
        mock_as_completed.return_value = [mock_future]

        result = parallel_process(["test"], lambda x, i, t: x)

        # Should handle the executor exception gracefully
        assert len(result) == 1
        assert result[0][0] is False  # success
        assert result[0][1] is None  # result
        assert isinstance(result[0][2], RuntimeError)  # exception


class TestSafeProcessItem:
    """Test cases for _safe_process_item function."""

    def test_safe_process_item_success(self) -> None:
        """Test _safe_process_item with successful processing."""
        mock_logger = Mock()
        result = _safe_process_item(lambda x, i, t: f"result_{x}", "test", 0, 1, mock_logger)

        assert result == (True, "result_test", None)
        mock_logger.error.assert_not_called()

    def test_safe_process_item_exception(self) -> None:
        """Test _safe_process_item when processing raises exception."""
        mock_logger = Mock()

        def failing_func(item, index, total):
            raise ValueError("Test error")

        result = _safe_process_item(failing_func, "test", 0, 1, mock_logger)

        assert result[0] is False  # success
        assert result[1] is None  # result
        assert isinstance(result[2], ValueError)
        assert str(result[2]) == "Test error"
        mock_logger.error.assert_called_once()

    def test_safe_process_item_different_exception_types(self) -> None:
        """Test _safe_process_item with different exception types."""
        mock_logger = Mock()

        exceptions = [
            ValueError("Value error"),
            TypeError("Type error"),
            KeyError("Key error"),
            RuntimeError("Runtime error"),
        ]

        for exc in exceptions:
            def failing_func(item, index, total):
                raise exc

            result = _safe_process_item(failing_func, "test", 0, 1, mock_logger)

            assert result[0] is False  # success
            assert result[1] is None  # result
            assert isinstance(result[2], type(exc))
            assert str(result[2]) == str(exc)

    def test_safe_process_item_with_index_and_total(self) -> None:
        """Test _safe_process_item passes index and total correctly."""
        mock_logger = Mock()

        def process_func(item, index, total):
            return f"{item}_{index}_{total}"

        result = _safe_process_item(process_func, "test", 2, 5, mock_logger)

        assert result == (True, "test_2_5", None)


class TestParallelDownloadNodes:
    """Test cases for parallel_download_nodes function."""

    def test_parallel_download_nodes_empty_list(self) -> None:
        """Test parallel_download_nodes with empty nodes list."""
        result = parallel_download_nodes([], lambda x, i, t: True)

        assert isinstance(result, DownloadResult)
        assert result.success is True
        assert result.message == "No nodes to download"

    def test_parallel_download_nodes_all_success(self) -> None:
        """Test parallel_download_nodes when all nodes succeed."""
        nodes = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

        def process_node(node, index, total):
            return True  # Success

        result = parallel_download_nodes(nodes, process_node)

        assert isinstance(result, DownloadResult)
        assert result.success is True
        assert result.message == "Successfully downloaded 3 episodes"

    def test_parallel_download_nodes_partial_success(self) -> None:
        """Test parallel_download_nodes with some successes and some failures."""
        nodes = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

        def process_node(node, index, total):
            # Simulate mixed results by returning True/False
            return node["id"] in ["1", "3"]  # 1 and 3 succeed, 2 fails

        result = parallel_download_nodes(nodes, process_node)

        assert isinstance(result, DownloadResult)
        # Should have some success since nodes 1 and 3 succeed
        assert result.success is True
        assert "episodes" in result.message

    def test_parallel_download_nodes_all_failure(self) -> None:
        """Test parallel_download_nodes when all nodes fail."""
        nodes = [{"id": "1"}, {"id": "2"}]

        def process_node(node, index, total):
            # Always fail with exceptions
            raise ValueError(f"Processing failed for {node['id']}")

        result = parallel_download_nodes(nodes, process_node)

        assert isinstance(result, DownloadResult)
        assert result.success is False  # None succeeded
        assert "episodes" in result.message

    def test_parallel_download_nodes_with_exceptions(self) -> None:
        """Test parallel_download_nodes when processing raises exceptions."""
        nodes = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

        def process_node(node, index, total):
            if node["id"] == "2":
                raise ValueError("Processing error")
            return True

        result = parallel_download_nodes(nodes, process_node)

        assert isinstance(result, DownloadResult)
        assert result.success is True  # Some succeeded
        assert "episodes" in result.message

    def test_parallel_download_nodes_with_custom_logger(self) -> None:
        """Test parallel_download_nodes with custom logger."""
        nodes = [{"id": "1"}]
        mock_logger = Mock()

        result = parallel_download_nodes(nodes, lambda x, i, t: True, logger=mock_logger)

        assert isinstance(result, DownloadResult)
        assert result.success is True
        # Should have used the provided logger

    def test_parallel_download_nodes_with_different_max_workers(self) -> None:
        """Test parallel_download_nodes with different max_workers."""
        nodes = [{"id": "1"}, {"id": "2"}]

        # Test with max_workers=1
        result = parallel_download_nodes(nodes, lambda x, i, t: True, max_workers=1)
        assert isinstance(result, DownloadResult)
        assert result.success is True

        # Test with max_workers=10
        result = parallel_download_nodes(nodes, lambda x, i, t: True, max_workers=10)
        assert isinstance(result, DownloadResult)
        assert result.success is True

    def test_parallel_download_nodes_complex_node_processing(self) -> None:
        """Test parallel_download_nodes with complex node processing."""
        nodes = [
            {"id": "1", "title": "Episode 1", "duration": 1800},
            {"id": "2", "title": "Episode 2", "duration": 2400},
            {"id": "3", "title": "Episode 3", "duration": 1200},
        ]

        def process_node(node, index, total):
            # Simulate processing that might fail based on duration
            if node["duration"] < 1500:
                raise ValueError("Episode too short")
            return True

        result = parallel_download_nodes(nodes, process_node)

        assert isinstance(result, DownloadResult)
        assert result.success is True  # 2 out of 3 succeeded
        assert result.message == "Downloaded 2 episodes with 1 errors"

    def test_parallel_download_nodes_single_success(self) -> None:
        """Test parallel_download_nodes when only one node succeeds."""
        nodes = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

        def process_node(node, index, total):
            return node["id"] == "2"  # Only second succeeds

        result = parallel_download_nodes(nodes, process_node)

        assert isinstance(result, DownloadResult)
        assert result.success is True  # At least one succeeded
        assert "episodes" in result.message

    def test_parallel_download_nodes_message_formatting(self) -> None:
        """Test parallel_download_nodes message formatting for different scenarios."""
        # Test singular vs plural
        nodes_single = [{"id": "1"}]
        result = parallel_download_nodes(nodes_single, lambda x, i, t: True)
        assert result.message == "Successfully downloaded 1 episodes"

        nodes_multiple = [{"id": "1"}, {"id": "2"}]
        result = parallel_download_nodes(nodes_multiple, lambda x, i, t: True)
        assert result.message == "Successfully downloaded 2 episodes"

        # Test error message formatting
        nodes_error = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

        def process_node(node, index, total):
            # Make all fail with exceptions
            raise ValueError("Processing failed")

        result = parallel_download_nodes(nodes_error, process_node)
        assert "episodes" in result.message
