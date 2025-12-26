import os
import re

REQUEST_TIMEOUT = 30


def sanitize_folder_name(name: str) -> str:
    """Sanitize a string to be used as a folder name.

    Args:
        name: The string to sanitize

    Returns:
        A sanitized string safe for use as a folder name

    """
    # Remove or replace characters that are problematic in folder names
    # Replace forward slashes and other problematic characters with underscores
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(" .")
    # Replace multiple spaces with single space
    sanitized = re.sub(r"\s+", " ", sanitized)
    # Limit length to avoid filesystem issues
    if len(sanitized) > 100:
        sanitized = sanitized[:100].rstrip()
    return sanitized


def load_graphql_query(filename: str) -> str:
    """Load GraphQL query from file.

    Args:
        filename: The GraphQL query filename

    Returns:
        The GraphQL query string

    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    graphql_dir = os.path.join(base_dir, "graphql")
    query_path = os.path.join(graphql_dir, filename)
    with open(query_path) as f:
        return f.read()
