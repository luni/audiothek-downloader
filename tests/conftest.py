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

    def raise_for_status(self) -> None:
        return None


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

        if operation_name == "ProgramSetsByEditorialCategoryId":
            offset = int(variables["offset"])
            count = int(variables["count"])
            has_next = offset == 0
            nodes = [
                {
                    "id": f"ps{offset + 1}",
                    "coreId": f"core_ps{offset + 1}",
                    "title": f"Program Set {offset + 1}",
                    "synopsis": "syn",
                    "numberOfElements": 10,
                    "image": {"url": "https://cdn.test/program_{width}.jpg", "url1X1": "https://cdn.test/program1x1_{width}.jpg"},
                    "editorialCategoryId": variables["editorialCategoryId"],
                },
                {
                    "id": f"ps{offset + 2}",
                    "coreId": f"core_ps{offset + 2}",
                    "title": f"Program Set {offset + 2}",
                    "synopsis": "syn",
                    "numberOfElements": 10,
                    "image": {"url": "https://cdn.test/program_{width}.jpg", "url1X1": "https://cdn.test/program1x1_{width}.jpg"},
                    "editorialCategoryId": variables["editorialCategoryId"],
                },
            ][:count]

            return {
                "data": {
                    "result": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": ""},
                        "totalCount": len(nodes) + (2 if has_next else 0),
                        "nodes": nodes,
                    }
                }
            }

        if operation_name == "EditorialCategoryCollections":
            offset = int(variables["offset"])
            count = int(variables["count"])
            has_next = offset == 0
            nodes = [
                {
                    "id": f"ec{offset + 1}",
                    "coreId": f"core_ec{offset + 1}",
                    "title": f"Editorial Collection {offset + 1}",
                    "synopsis": "syn",
                    "summary": "sum",
                    "image": {"url": "https://cdn.test/collection_{width}.jpg", "url1X1": "https://cdn.test/collection1x1_{width}.jpg"},
                    "sharingUrl": "https://example.com/share/ec1",
                    "path": "/collection/ec1",
                    "numberOfElements": 4,
                    "broadcastDuration": 3600,
                },
                {
                    "id": f"ec{offset + 2}",
                    "coreId": f"core_ec{offset + 2}",
                    "title": f"Editorial Collection {offset + 2}",
                    "synopsis": "syn",
                    "summary": "sum",
                    "image": {"url": "https://cdn.test/collection_{width}.jpg", "url1X1": "https://cdn.test/collection1x1_{width}.jpg"},
                    "sharingUrl": "https://example.com/share/ec2",
                    "path": "/collection/ec2",
                    "numberOfElements": 4,
                    "broadcastDuration": 3600,
                },
            ][:count]

            return {
                "data": {
                    "result": {
                        "id": variables["id"],
                        "title": "Category",
                        "sections": [{"nodes": nodes}],
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
                # Include program set metadata
                result_container = {
                    "id": "ps1",
                    "coreId": "core_ps1",
                    "title": "Test Program Set",
                    "synopsis": "Test program set synopsis",
                    "numberOfElements": 4,
                    "image": {"url": "https://cdn.test/program_{width}.jpg", "url1X1": "https://cdn.test/program1x1_{width}.jpg"},
                    "editorialCategoryId": "cat123",
                    "imageCollectionId": "img123",
                    "publicationServiceId": 1,
                    "coreDocument": {"key": "value"},
                    "rowId": 1,
                    "nodeId": "node_ps1",
                    "items": {"pageInfo": {"hasNextPage": has_next, "endCursor": ""}, "nodes": nodes}
                }
            else:
                # Include editorial collection metadata
                result_container = {
                    "id": "ec1",
                    "coreId": "core_ec1",
                    "title": "Test Editorial Collection",
                    "synopsis": "Test editorial collection synopsis",
                    "summary": "Test editorial collection summary",
                    "editorialDescription": "Test editorial description",
                    "image": {"url": "https://cdn.test/collection_{width}.jpg", "url1X1": "https://cdn.test/collection1x1_{width}.jpg"},
                    "sharingUrl": "https://example.com/share/ec1",
                    "path": "/collection/ec1",
                    "numberOfElements": 4,
                    "broadcastDuration": 3600,
                    "items": {"pageInfo": {"hasNextPage": has_next}, "nodes": nodes}
                }

            return {"data": {"result": result_container}}

        raise AssertionError(f"Unhandled operation: {operation_name}")


@pytest.fixture(scope="session")
def graphql_schema() -> GraphQLSchema:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(base_dir, "src", "audiothek", "graphql", "schema.graphql")
    with open(schema_path) as f:
        sdl = f.read()
    return build_schema(sdl)


@pytest.fixture()
def graphql_mock(graphql_schema: GraphQLSchema) -> GraphQLMock:
    return GraphQLMock(graphql_schema)


@pytest.fixture()
def mock_requests_get(monkeypatch: pytest.MonkeyPatch, graphql_mock: GraphQLMock) -> Callable[..., MockResponse]:
    def _mock_session_get(self, url: str, params: dict[str, Any] | None = None, timeout: int | None = None, **kwargs: Any) -> MockResponse:  # noqa: ARG001
        if url == "https://api.ardaudiothek.de/graphql":
            assert params is not None
            query = params["query"]
            variables = json.loads(params["variables"])
            payload = graphql_mock.handle(query, variables)
            return MockResponse(_json=payload)

        if url.startswith("https://cdn.test/"):
            return MockResponse(content=b"binary")

        raise AssertionError(f"Unexpected URL requested: {url}")

    # Mock the Session.get method instead of requests.get
    monkeypatch.setattr("requests.Session.get", _mock_session_get)
    return _mock_session_get
