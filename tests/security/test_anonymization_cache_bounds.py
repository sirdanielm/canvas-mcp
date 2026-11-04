"""Bounded pseudonym retention must never determine generated identities."""

import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP

from canvas_mcp.core import anonymization, config, credentials
from canvas_mcp.tools.admin_tools import register_admin_tools


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    credentials.clear_http_request_context()
    monkeypatch.setattr(anonymization, "_anonymization_cache", {})
    yield
    credentials.clear_http_request_context()


@pytest.fixture(params=["stdio", "http"])
def cache_scope(request: pytest.FixtureRequest) -> Iterator[None]:
    if request.param == "http":
        credentials.set_http_request_active()
        credentials.set_request_credentials(credentials.RequestCredentials(
            "synthetic-token", "https://canvas.example/api/v1",
        ))
    yield


def expected(identifier: str | int, prefix: str = "Student") -> str:
    return f"{prefix}_{hashlib.sha256(str(identifier).encode()).hexdigest()[:8]}"


def test_retention_is_bounded_and_eviction_preserves_identity(cache_scope: None) -> None:
    first = anonymization.generate_anonymous_id("synthetic-first")
    for number in range(4096):
        assert anonymization.generate_anonymous_id(number) == expected(number)

    stats = anonymization.get_anonymization_stats()
    assert stats["total_anonymized_ids"] == 4096
    assert stats["count_scope"] == "retained_cache_entries"
    assert stats["cache_capacity"] == 4096
    assert len(stats["sample_mappings"]) == 3
    assert "synthetic-first" not in anonymization._session_cache()
    assert anonymization.generate_anonymous_id("synthetic-first") == first
    assert anonymization.get_anonymization_stats()["total_anonymized_ids"] == 4096


def test_prefix_is_deterministic_before_and_after_eviction_or_clear(cache_scope: None) -> None:
    assert anonymization.generate_anonymous_id(17) == "Student_4523540f"
    assert anonymization.generate_anonymous_id(17, "Reviewer") == "Reviewer_4523540f"
    for number in range(4096):
        anonymization.generate_anonymous_id(f"synthetic-{number}")
    assert anonymization.generate_anonymous_id(17, "Reviewer") == "Reviewer_4523540f"
    assert anonymization.generate_anonymous_id(17) == "Student_4523540f"
    anonymization.clear_anonymization_cache()
    assert anonymization.get_anonymization_stats()["total_anonymized_ids"] == 0
    assert anonymization.generate_anonymous_id(17) == "Student_4523540f"


@pytest.mark.parametrize("identifier,prefix", [
    ("x" * 65, "Student"),
    ("x", "R" * 33),
    ("\U0001f9ea" * 65, "Student"),
])
def test_oversized_inputs_are_not_retained_but_keep_same_pseudonym(
    cache_scope: None, identifier: str, prefix: str,
) -> None:
    for _ in range(2):
        assert anonymization.generate_anonymous_id(identifier, prefix) == expected(identifier, prefix)
    assert anonymization.get_anonymization_stats()["total_anonymized_ids"] == 0
    assert anonymization._session_cache() == {}


def test_maximum_unicode_entries_have_a_fixed_retained_payload_budget(cache_scope: None) -> None:
    prefix = "\U0001f9ea" * 32
    for number in range(4097):
        identifier = "\U0001f9ea" * 60 + f"{number:04}"
        anonymization.generate_anonymous_id(identifier, prefix)
    cache = anonymization._session_cache()
    assert len(cache) == 4096
    # At most 64 four-byte codepoints in the key; 32 in the prefix plus 9 ASCII
    # pseudonym suffix bytes. Python object overhead is bounded by entry count.
    assert all(len(key) <= 64 and len(value) <= 41 for key, value in cache.items())
    assert sum(len(key.encode()) + len(value.encode()) for key, value in cache.items()) <= 4096 * 393


@pytest.mark.parametrize("field", ["identifier", "prefix"])
def test_string_subclasses_cannot_bypass_retention_bounds(cache_scope: None, field: str) -> None:
    class MisreportedText(str):
        def __len__(self) -> int:
            return 1

        def __str__(self) -> str:
            return self

        def __format__(self, spec: str) -> str:
            return self

    identifier = MisreportedText("x" * 65) if field == "identifier" else "synthetic"
    prefix = MisreportedText("R" * 33) if field == "prefix" else "Student"
    assert anonymization.generate_anonymous_id(identifier, prefix) == expected(identifier, prefix)
    assert anonymization.get_anonymization_stats()["total_anonymized_ids"] == 0


def test_retention_never_keeps_string_subclass_attributes(cache_scope: None) -> None:
    class DecoratedText(str):
        extra: object

        def __str__(self) -> str:
            return self

    identifier = DecoratedText("synthetic")
    identifier.extra = object()
    anonymization.generate_anonymous_id(identifier)
    assert type(next(iter(anonymization._session_cache()))) is str


def test_summary_counts_only_the_active_request_retention() -> None:
    anonymization.generate_anonymous_id(9001)
    anonymization.generate_anonymous_id(9002)
    credentials.set_http_request_active()
    credentials.set_request_credentials(credentials.RequestCredentials(
        "synthetic-token", "https://canvas.example/api/v1",
    ))
    anonymization.generate_anonymous_id(101)
    summary = anonymization.create_anonymization_summary(1, 1, "users")
    assert "Cached pseudonym mappings: 1" in summary
    assert "Cached pseudonym mappings: 2" not in summary


def test_concurrent_stdio_retention_remains_bounded() -> None:
    def generate(number: int) -> tuple[bool, int]:
        output = anonymization.generate_anonymous_id(number)
        size = anonymization.get_anonymization_stats()["total_anonymized_ids"]
        return output == expected(number), size

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(generate, range(6000)))
    assert all(correct and size <= 4096 for correct, size in results)
    assert anonymization.get_anonymization_stats()["total_anonymized_ids"] == 4096


async def test_status_labels_retained_mappings_without_claiming_lifetime_uniqueness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "get_config", lambda: SimpleNamespace(
        enable_data_anonymization=True, anonymization_debug=False,
    ))
    anonymization.generate_anonymous_id(101)
    server = FastMCP("synthetic-anonymization-status")
    register_admin_tools(server)
    async with Client(server) as client:
        result = await client.call_tool("get_anonymization_status", {})
    text = result.content[0].text
    assert "Cached pseudonym mappings: 1" in text
    assert "not a lifetime unique-student count" in text
    assert "Total unique students anonymized" not in text
