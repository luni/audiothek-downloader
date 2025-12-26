"""Custom exceptions for the audiothek-downloader."""


class AudiothekError(Exception):
    """Base exception for all audiothek-downloader errors."""

    pass


class ResourceNotFoundError(AudiothekError):
    """Exception raised when a resource is not found."""

    def __init__(self, resource_id: str, resource_type: str | None = None) -> None:
        """Initialize the exception.

        Args:
            resource_id: The ID of the resource that was not found
            resource_type: The type of resource (episode, program, collection)

        """
        self.resource_id = resource_id
        self.resource_type = resource_type
        message = f"Resource not found: {resource_id}"
        if resource_type:
            message = f"{resource_type.capitalize()} not found: {resource_id}"
        super().__init__(message)


class ResourceParseError(AudiothekError):
    """Exception raised when a resource cannot be parsed."""

    def __init__(self, url_or_id: str, message: str | None = None) -> None:
        """Initialize the exception.

        Args:
            url_or_id: The URL or ID that could not be parsed
            message: Additional error message

        """
        self.url_or_id = url_or_id
        msg = f"Could not parse resource: {url_or_id}"
        if message:
            msg = f"{msg} - {message}"
        super().__init__(msg)


class DownloadError(AudiothekError):
    """Exception raised when a download fails."""

    def __init__(self, url: str, status_code: int | None = None, message: str | None = None) -> None:
        """Initialize the exception.

        Args:
            url: The URL that could not be downloaded
            status_code: The HTTP status code if available
            message: Additional error message

        """
        self.url = url
        self.status_code = status_code
        msg = f"Failed to download: {url}"
        if status_code:
            msg = f"{msg} (Status: {status_code})"
        if message:
            msg = f"{msg} - {message}"
        super().__init__(msg)


class FileOperationError(AudiothekError):
    """Exception raised when a file operation fails."""

    def __init__(self, file_path: str, operation: str, message: str | None = None) -> None:
        """Initialize the exception.

        Args:
            file_path: The path to the file that caused the error
            operation: The operation that failed (e.g., "read", "write", "create")
            message: Additional error message

        """
        self.file_path = file_path
        self.operation = operation
        msg = f"Failed to {operation} file: {file_path}"
        if message:
            msg = f"{msg} - {message}"
        super().__init__(msg)


class GraphQLError(AudiothekError):
    """Exception raised when a GraphQL query fails."""

    def __init__(self, query_name: str, variables: dict | None = None, message: str | None = None) -> None:
        """Initialize the exception.

        Args:
            query_name: The name of the GraphQL query that failed
            variables: The variables used in the query
            message: Additional error message

        """
        self.query_name = query_name
        self.variables = variables
        msg = f"GraphQL query failed: {query_name}"
        if message:
            msg = f"{msg} - {message}"
        super().__init__(msg)
