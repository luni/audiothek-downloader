"""Parallel processing utilities for audiothek-downloader."""

import concurrent.futures
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from .models import DownloadResult

T = TypeVar("T")


def parallel_process(
    items: list[Any],
    process_func: Callable[[Any, int, int], T],
    max_workers: int = 4,
    logger: logging.Logger | None = None,
) -> list[tuple[bool, T | None, Exception | None]]:
    """Process items in parallel using ThreadPoolExecutor.

    Args:
        items: List of items to process
        process_func: Function to process each item, takes (item, index, total_count)
        max_workers: Maximum number of workers to use
        logger: Logger instance for logging messages

    Returns:
        List of tuples (success, result, exception) for each item

    """
    if not items:
        return []

    if logger is None:
        logger = logging.getLogger(__name__)

    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_index = {executor.submit(_safe_process_item, process_func, item, i, len(items), logger): i for i, item in enumerate(items)}

        # Process results as they complete
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                success, result, exception = future.result()
                results.append((success, result, exception))
                if success:
                    logger.debug("Successfully processed item %s of %s", index + 1, len(items))
                else:
                    logger.warning("Failed to process item %s of %s: %s", index + 1, len(items), exception)
            except Exception as e:
                logger.error("Error getting result for item %s: %s", index + 1, e)
                results.append((False, None, e))

    # Sort results by original index
    return results


def _safe_process_item(
    process_func: Callable[[Any, int, int], T],
    item: object,  # Use object instead of Any to avoid linting error
    index: int,
    total_count: int,
    logger: logging.Logger,
) -> tuple[bool, T | None, Exception | None]:
    """Safely process an item, catching any exceptions.

    Args:
        process_func: Function to process the item
        item: Item to process
        index: Index of the item
        total_count: Total number of items
        logger: Logger instance for logging messages

    Returns:
        Tuple of (success, result, exception)

    """
    try:
        result = process_func(item, index, total_count)
        return True, result, None
    except Exception as e:
        logger.error("Error processing item %s of %s: %s", index + 1, total_count, e)
        return False, None, e


def parallel_download_nodes(
    nodes: list[dict[str, Any]],
    process_node_func: Callable[[dict[str, Any], int, int], bool],
    max_workers: int = 4,
    logger: logging.Logger | None = None,
) -> DownloadResult:
    """Download nodes in parallel.

    Args:
        nodes: List of nodes to download
        process_node_func: Function to process each node, takes (node, index, total_count)
        max_workers: Maximum number of workers to use
        logger: Logger instance for logging messages

    Returns:
        DownloadResult with success status and message

    """
    if not nodes:
        return DownloadResult(success=True, message="No nodes to download")

    if logger is None:
        logger = logging.getLogger(__name__)

    results = parallel_process(nodes, process_node_func, max_workers, logger)

    success_count = sum(1 for success, _, _ in results if success)
    error_count = len(results) - success_count

    if error_count > 0:
        return DownloadResult(success=success_count > 0, message=f"Downloaded {success_count} episodes with {error_count} errors")
    return DownloadResult(success=True, message=f"Successfully downloaded {success_count} episodes")
