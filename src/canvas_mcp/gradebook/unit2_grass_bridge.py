"""Pinned GrAss validation and native arithmetic for fictional in-memory proofs.

Caller-supplied code paths and hashes are reviewed dependencies, not authority.
No Store, source-media loader, native import/adoption, or delivery is exposed.
"""

from __future__ import annotations

import ast
import hashlib
import re
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from .model import GradebookError


def _need(value: bool, message: str) -> None:
    if not value:
        raise GradebookError(message)


def _main_guard(node: ast.stmt) -> bool:
    """Recognize only the conventional non-imported CLI entry point."""
    if not isinstance(node, ast.If) or node.orelse:
        return False
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == len(test.comparators) == 1
        and isinstance(test.ops[0], ast.Eq)
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def load_pinned_module(path: Path, expected_sha256: str) -> ModuleType:
    """Load explicitly reviewed definition-only source without bytecode writes.

    This is an integrity check for trusted code, not a Python security sandbox.
    Module-level execution is limited to definitions, imports and constants.
    A conventional main guard is excluded, so loading never runs its CLI.
    """
    path = Path(path).absolute()
    _need(
        path.is_file() and path.resolve() == path and not path.is_symlink(),
        "Direct reviewed code file required.",
    )
    _need(
        type(expected_sha256) is str
        and re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is not None,
        "Exact reviewed code digest required.",
    )
    raw = path.read_bytes()
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256, "Pinned code changed.")
    tree = ast.parse(raw, filename=str(path))
    for node in tree.body:
        if _main_guard(node):
            continue
        if isinstance(node, ast.Expr):
            _need(
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str),
                "Definition-only module required.",
            )
        else:
            _need(
                isinstance(
                    node,
                    (
                        ast.Import,
                        ast.ImportFrom,
                        ast.Assign,
                        ast.AnnAssign,
                        ast.FunctionDef,
                        ast.ClassDef,
                    ),
                ),
                "Definition-only module required.",
            )
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    _need(
                        isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "re"
                        and child.func.attr == "compile",
                        "Module initializer is outside reviewed constants.",
                    )
    module = ModuleType("_unit2_pinned_" + expected_sha256)
    module.__file__ = str(path)
    module.__dict__["_reviewed_source_bytes"] = raw
    tree.body = [node for node in tree.body if not _main_guard(node)]
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


def validate_decision(
    *,
    bridge_path: Path,
    bridge_sha256: str,
    snapshot: dict[str, Any],
    decision: dict[str, Any],
    demo_ledger: dict[str, Any],
) -> dict[str, Any]:
    """Use the frozen producer validator; never treat actor text as acceptance."""
    bridge = load_pinned_module(bridge_path, bridge_sha256)
    _need(
        getattr(bridge, "CONTRACT_ID", None) == "grass.unit2.mc-teacher-decision.v1.1",
        "Frozen GrAss v1.1 required.",
    )
    result = bridge.validate_plan(
        deepcopy(snapshot), deepcopy(decision), deepcopy(demo_ledger)
    )
    _need(
        type(result) is dict and type(result.get("plan")) is dict,
        "Native validation result required.",
    )
    plan = result["plan"]
    _need(
        plan.get("native_import_allowed") is False
        and plan.get("teacher_accepted") is False
        and plan.get("publication_authorized") is False,
        "Native plan must remain unaccepted and import-disabled.",
    )
    return deepcopy(result)


def _arithmetic(native: ModuleType) -> Any:
    """Extract the unchanged score arithmetic before its first persistence gate."""
    tree = ast.parse(native.__dict__["_reviewed_source_bytes"])
    score = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "score"),
        None,
    )
    _need(score is not None, "Native score function required.")
    assert isinstance(score, ast.FunctionDef)
    starts = [
        i
        for i, n in enumerate(score.body)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "awards" for t in n.targets)
    ]
    stops = [
        i
        for i, n in enumerate(score.body)
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and isinstance(n.value.func.value, ast.Name)
        and n.value.func.value.id == "budget"
        and n.value.func.attr == "check"
    ]
    _need(
        len(starts) == len(stops) == 1 and starts[0] < stops[0],
        "Reviewed native arithmetic boundary changed.",
    )
    body = deepcopy(score.body[starts[0] : stops[0]])
    forbidden = {"store", "budget", "open", "Path", "subprocess", "os", "httpx"}
    _need(
        not any(
            isinstance(n, ast.Name) and n.id in forbidden
            for node in body
            for n in ast.walk(node)
        ),
        "I/O reference in native arithmetic boundary.",
    )
    names = [
        "judgment",
        "reading",
        "form",
        "spec",
        "packet",
        "packet_id",
        "head",
        "policy_raw",
        "operations",
        "mark_rule",
    ]
    function = ast.FunctionDef(
        name="_fictional_native_arithmetic",
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg=n) for n in names],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=body + [ast.Return(value=ast.Name(id="result", ctx=ast.Load()))],
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    scope = dict(native.__dict__)
    exec(compile(module, str(native.__file__) + ":pure-arithmetic", "exec"), scope)
    return scope[function.name]


def recompute_fictional(
    *,
    bridge_path: Path,
    bridge_sha256: str,
    pipeline_path: Path,
    pipeline_sha256: str,
    snapshot: dict[str, Any],
    decision: dict[str, Any],
    demo_ledger: dict[str, Any],
    reading: dict[str, Any],
    judgment: dict[str, Any] | None,
    form: dict[str, Any],
    policy_spec: dict[str, Any],
    packet: dict[str, Any],
    head: dict[str, Any],
    policy_raw: bytes,
    operations: list[dict[str, Any]],
    fixture_only: bool = False,
    use_mark_attempt_rule: bool = False,
) -> dict[str, Any]:
    """Run actual pinned native arithmetic on an explicitly fictional packet.

    Schema inputs are the producer's saved reading/items, judgment/awards, form/
    questions, validated policy spec/items and grade operations. No schema or
    academic rule is invented here. The unchanged native result retains all
    deductions, holds and criteria for the existing SDM formatter.
    """
    _need(
        fixture_only is True
        and decision.get("mode") == "DEMO"
        and packet.get("assessment_id") == "FICTIONAL_DEMO_ONLY",
        "Explicit fully fictional DEMO fixture required.",
    )
    validated = validate_decision(
        bridge_path=bridge_path,
        bridge_sha256=bridge_sha256,
        snapshot=snapshot,
        decision=decision,
        demo_ledger=demo_ledger,
    )
    native = load_pinned_module(pipeline_path, pipeline_sha256)
    calculate = _arithmetic(native)
    binding = snapshot["binding"]
    _need(
        packet.get("packet_id") == binding["packet_id"]
        and packet.get("source_sha256") == binding["source_sha256"]
        and packet.get("form_id") == binding["form_id"]
        and packet.get("attempt") == binding["attempt"] == "R1"
        and head.get("reading_key") == binding["reading_key"]
        and head.get("result_key") == binding["result_key"]
        and hashlib.sha256(policy_raw).hexdigest() == binding["policy_sha256"],
        "Fictional native inputs disagree with decision bindings.",
    )
    before_reading = deepcopy(reading)
    matching = [
        i
        for i, item in enumerate(before_reading["items"])
        if item["item_id"] == binding["item_id"]
    ]
    _need(
        len(matching) == 1
        and before_reading["items"][matching[0]] == snapshot["current_item"],
        "Fictional saved item differs from native decision prestate.",
    )
    after_reading = deepcopy(before_reading)
    after_reading["items"][matching[0]] = deepcopy(validated["plan"]["after_item"])

    def compute(value: dict[str, Any]) -> dict[str, Any]:
        result = calculate(
            deepcopy(judgment),
            deepcopy(value),
            deepcopy(form),
            deepcopy(policy_spec),
            deepcopy(packet),
            packet["packet_id"],
            deepcopy(head),
            policy_raw,
            deepcopy(operations),
            use_mark_attempt_rule,
        )
        _need(
            type(result) is dict
            and result.get("teacher_acceptance") == "NOT_ACCEPTED"
            and result.get("publication_status") == "NOT_AUTHORIZED"
            and all(v is False for v in result.get("gates", {}).values()),
            "Native fictional result must remain unaccepted.",
        )
        return cast(dict[str, Any], result)

    before, after = compute(before_reading), compute(after_reading)
    return {
        "status": "DEMO_NOT_TEACHER_ACCEPTED",
        "fixture_only": True,
        "validated_plan": validated,
        "before_result": before,
        "after_result": after,
        "before_reading": before_reading,
        "after_reading": after_reading,
        "native_arithmetic_recomputed": True,
        "native_import_allowed": False,
        "teacher_accepted": False,
        "publication_allowed": False,
        "store_writes": 0,
        "canvas_writes": 0,
        "sheet_writes": 0,
        "paid_calls": 0,
    }
