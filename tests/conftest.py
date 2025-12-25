import json
import os
from dataclasses import dataclass
from typing import Any, Callable

import pytest
from graphql import GraphQLSchema, build_schema, parse, validate


@dataclass
class MockResponse:
    _json: dict[str, Any] | None = None
    content: bytes = b""

    def json(self) -> dict[str, Any]:
        if self._json is None:
            raise ValueError("No JSON payload configured")
        return self._json


class GraphQLMock:
    def __init__(self, schema: GraphQLSchema) -> None:
        self.schema = schema
        self.calls: list[dict[str, Any]] = []

    def handle(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        document = parse(query)
        errors = validate(self.schema, document)
        if errors:
            raise AssertionError("GraphQL query did not validate against schema: " + "; ".join(str(e) for e in errors))

        operation_name = None
        for definition in document.definitions:
            if getattr(definition, "name", None) is not None:
                operation_name = definition.name.value
                break

        self.calls.append({"operation": operation_name, "variables": variables})

        if operation_name == "EpisodeQuery":
            episode_id = variables["id"]
            return {
                "data": {
                    "result": {
                        "id": episode_id,
                        "title": "Test Episode",
                        "description": "desc",
                        "summary": "sum",
                        "duration": 123,
                        "publishDate": "2020-01-01T00:00:00Z",
                        "image": {"url": "https://cdn.test/image_{width}.jpg", "url1X1": "https://cdn.test/image1x1_{width}.jpg"},
                        "programSet": {"id": "ps1", "title": "Prog", "path": "/p"},
                        "audios": [{"downloadUrl": "https://cdn.test/audio.mp3", "url": "https://cdn.test/audio_alt.mp3"}],
                    }
                }
            }

        if operation_name in {"ProgramSetEpisodesQuery", "EpisodesQuery"}:
            offset = int(variables["offset"])
            count = int(variables["count"])
            # Return two pages: offset=0 has next page, offset>=count ends
            has_next = offset == 0
            nodes = [
                {
                    "id": f"e{offset + 1}",
                    "title": f"Episode {offset + 1}",
                    "description": "d",
                    "summary": "s",
                    "duration": 1,
                    "publishDate": "2020-01-01T00:00:00Z",
                    "image": {"url": "https://cdn.test/image_{width}.jpg", "url1X1": "https://cdn.test/image1x1_{width}.jpg"},
                    "programSet": {"id": "ps1", "title": "Prog", "path": "/p"},
                    "audios": [{"downloadUrl": "https://cdn.test/audio.mp3"}],
                },
                {
                    "id": f"e{offset + 2}",
                    "title": f"Episode {offset + 2}",
                    "description": "d",
                    "summary": "s",
                    "duration": 1,
                    "publishDate": "2020-01-01T00:00:00Z",
                    "image": {"url": "https://cdn.test/image_{width}.jpg", "url1X1": "https://cdn.test/image1x1_{width}.jpg"},
                    "programSet": {"id": "ps1", "title": "Prog", "path": "/p"},
                    "audios": [{"downloadUrl": "https://cdn.test/audio.mp3"}],
                },
            ]

            result_container: dict[str, Any]
            if operation_name == "ProgramSetEpisodesQuery":
                result_container = {"items": {"pageInfo": {"hasNextPage": has_next, "endCursor": ""}, "nodes": nodes}}
            else:
                result_container = {"items": {"pageInfo": {"hasNextPage": has_next}, "nodes": nodes}}

            return {"data": {"result": result_container}}

        raise AssertionError(f"Unhandled operation: {operation_name}")


@pytest.fixture(scope="session")
def graphql_schema() -> GraphQLSchema:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(base_dir, "graphql", "schema.graphql")
    with open(schema_path) as f:
        sdl = f.read()
    return build_schema(sdl)


@pytest.fixture()
def graphql_mock(graphql_schema: GraphQLSchema) -> GraphQLMock:
    return GraphQLMock(graphql_schema)


@pytest.fixture()
def mock_requests_get(monkeypatch: pytest.MonkeyPatch, graphql_mock: GraphQLMock) -> Callable[..., MockResponse]:
    def _mock_get(url: str, params: dict[str, Any] | None = None, timeout: int | None = None) -> MockResponse:  # noqa: ARG001
        if url == "https://api.ardaudiothek.de/graphql":
            assert params is not None
            query = params["query"]
            variables = json.loads(params["variables"])
            payload = graphql_mock.handle(query, variables)
            return MockResponse(_json=payload)

        if url.startswith("https://cdn.test/"):
            return MockResponse(content=b"binary")

        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setattr("requests.get", _mock_get)
    return _mock_get
