"""Independent effect and authority boundaries; fictional in-memory records only."""

from __future__ import annotations

import builtins
import copy
import importlib.util
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast, get_type_hints

import httpx
import pytest
from test_gradebook_proposal_preview import repin
from test_gradebook_proposal_preview import scenario as scenario

from canvas_mcp.gradebook import proposal_preview as preview
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store

APPROVAL_FIELDS = (
    "teacher_approval",
    "score_approval",
    "comment_approval",
    "publication_allowed",
)


@contextmanager
def no_effects(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Allow inert imports, but forbid activating clients, stores or transports."""
    effects: list[str] = []

    def blocked(label: str) -> Any:
        def fail(*args: Any, **kwargs: Any) -> Any:
            effects.append(label)
            raise AssertionError("Preview attempted an effect: " + label)

        return fail

    original_import = builtins.__import__
    forbidden_modules = (
        "sdm_canvas_launcher",
        "sdm_gradebook_worker",
        "sdm_teacher_edit_runtime",
        "canvas_mcp.gradebook.server",
        "canvas_mcp.gradebook.worker",
        "canvas_mcp.gradebook.get_refresh_control",
        "canvas_mcp.gradebook.google",
        "canvas_mcp.gradebook.runtime_diagnostics",
        "canvas_mcp.gradebook.text_comments_mcp",
        "canvas_mcp.gradebook.localgrass_application",
        "canvas_mcp.gradebook.publish",
        "google.auth",
        "google.cloud",
        "vertexai",
        "openai",
        "anthropic",
        "keyring",
    )

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        absolute = name
        if level:
            absolute = importlib.util.resolve_name(
                "." * level + name, (globals or {}).get("__package__", "")
            )
        if any(
            absolute == module or absolute.startswith(module + ".")
            for module in forbidden_modules
        ):
            return blocked("controller/provider import")()
        return original_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as patch:
        patch.setattr(sys, "dont_write_bytecode", True)
        patch.setattr(builtins, "__import__", guarded_import)
        patch.setattr(builtins, "open", blocked("file open"))
        for method in (
            "open",
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
            "mkdir",
            "touch",
            "unlink",
            "rename",
            "replace",
            "chmod",
        ):
            patch.setattr(Path, method, blocked("filesystem access"))
        for method in (
            "open",
            "mkdir",
            "makedirs",
            "remove",
            "unlink",
            "rename",
            "replace",
            "chmod",
            "link",
            "symlink",
            "system",
        ):
            patch.setattr(os, method, blocked("filesystem/process access"))
        patch.setattr(Store, "__init__", blocked("Store construction"))
        patch.setattr(
            GradebookClient, "__init__", blocked("Canvas client construction")
        )
        patch.setattr(httpx.Client, "__init__", blocked("HTTP client construction"))
        patch.setattr(
            httpx.AsyncClient, "__init__", blocked("HTTP client construction")
        )
        patch.setattr(socket.socket, "__init__", blocked("socket construction"))
        patch.setattr(socket, "create_connection", blocked("network connection"))
        patch.setattr(socket, "getaddrinfo", blocked("network resolution"))
        patch.setattr(subprocess, "Popen", blocked("subprocess construction"))
        yield effects


class RecordingStore:
    """An in-memory save observer, never a filesystem Store."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reference = ("f" * 64, Path("fictional-review.json"))

    def save(self, kind: str, value: dict[str, Any]) -> tuple[str, Path]:
        self.calls.append((kind, copy.deepcopy(value)))
        return self.reference


def test_fresh_import_and_public_annotations_activate_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(preview.__file__).resolve()
    spec = importlib.util.spec_from_file_location(
        "canvas_mcp.gradebook.fictional_preview_boundary", source
    )
    assert spec is not None and spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)
    with no_effects(monkeypatch) as effects:
        spec.loader.exec_module(fresh)
        hints = get_type_hints(fresh.save_preview)
    assert effects == []
    assert hints["store"] is Store
    assert fresh.CONTRACT == preview.CONTRACT


@pytest.mark.parametrize("case", ["ready", "formative", "held", "excluded"])
def test_each_preview_path_is_inert_and_only_saves_an_unapproved_review(
    scenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    binding = scenario["assignment_bindings"][0]
    if case == "formative":
        scenario["proposals"][0].update(source_lane="SDMGRASS_FORMATIVE", feedback=None)
        binding["source_lane"] = "SDMGRASS_FORMATIVE"
        repin(scenario)
    elif case == "held":
        binding["assessment_floor"] = 80
    elif case == "excluded":
        binding["assignment_metadata"].update(
            submission_types=["external_tool"],
            external_tool_tag_attributes={"url": "https://edpuzzle.com/fictional"},
        )
        binding["assignment_metadata_sha256"] = digest(binding["assignment_metadata"])
    before = copy.deepcopy(scenario)
    store = RecordingStore()
    with no_effects(monkeypatch) as effects:
        plan = preview.prepare_preview(**scenario)
        result = preview.save_preview(cast(Store, store), plan)
    assert effects == [] and scenario == before
    assert result == store.reference
    assert store.calls == [("review", plan)]
    assert plan["review_state"] == "UNAPPROVED"
    assert plan["requests"] == [] and plan["canvas_writes"] == 0
    assert all(plan[field] is False for field in APPROVAL_FIELDS)
    if case == "formative":
        assert list(plan["delivery_policies"].values()) == ["SCORE_ONLY"]
        assert plan["proposals"][0]["feedback"] is None
    elif case in {"held", "excluded"}:
        assert plan["envelope"]["edits"] == []
        collection = (
            plan["held_proposals"] if case == "held" else plan["excluded_inventory"]
        )
        assert collection[0]["review_state"] == "HELD"
        assert collection[0]["documentary_only"] is True
        assert all(collection[0][field] is False for field in APPROVAL_FIELDS)
        if case == "excluded":
            assert "proposal" not in collection[0] and "feedback" not in collection[0]


@pytest.mark.parametrize("field", [*APPROVAL_FIELDS, "requests"])
def test_rehashing_cannot_turn_preview_into_approval_or_write_requests(
    scenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    plan = preview.prepare_preview(**scenario)
    plan[field] = [{"method": "PUT"}] if field == "requests" else True
    plan["preview_id"] = digest(
        {key: value for key, value in plan.items() if key != "preview_id"}
    )
    store = RecordingStore()
    with no_effects(monkeypatch) as effects:
        with pytest.raises(GradebookError, match="^PROPOSAL_PREVIEW_CHANGED$"):
            preview.save_preview(cast(Store, store), plan)
    assert effects == [] and store.calls == []


def test_rehashing_documentary_hold_cannot_add_edits(
    scenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario["assignment_bindings"][0]["assessment_floor"] = 80
    plan = preview.prepare_preview(**scenario)
    plan["held_proposals"][0]["edits"] = [{"value": 73}]
    plan["preview_id"] = digest(
        {key: value for key, value in plan.items() if key != "preview_id"}
    )
    store = RecordingStore()
    with no_effects(monkeypatch) as effects:
        with pytest.raises(GradebookError, match="^PROPOSAL_PREVIEW_CHANGED$"):
            preview.save_preview(cast(Store, store), plan)
    assert effects == [] and store.calls == []
