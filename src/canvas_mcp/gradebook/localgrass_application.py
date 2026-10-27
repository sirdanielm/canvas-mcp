"""Explicit application wiring over existing authorities; no service activation.

The CLI checks private configuration only. It opens no database, creates no
schema/client/account and makes no network call. An already running application
may pass its existing objects to build_application; staging defaults to off.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import GradebookClient, GradebookError
from .google import GoogleSheets
from .localgrass_edit_owner import LocalGrAssEditOwner
from .localgrass_teacher_edit import LocalGrAssEditConnection
from .store import Store
from .worker import RefreshJournal

CONTRACT = "LOCALGRASS_EDIT_APPLICATION_V1"
UNIT1_CONTRACT = "LOCALGRASS_EDIT_UNIT1_APPLICATION_V1"
PROPOSAL_CONTRACT = "LOCALGRASS_PROPOSAL_EDIT_APPLICATION_V1"
UNIT1_PROPOSAL_CONTRACT = "LOCALGRASS_PROPOSAL_EDIT_UNIT1_APPLICATION_V1"
HASH = re.compile(r"[a-f0-9]{64}\Z")
FIELDS = {
    "contract",
    "decision_id",
    "source_receipt_id",
    "section",
    "source_root",
    "identity_runtime_root",
    "shared_tool",
    "staging_config_path",
    "staging_config_sha256",
}


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _path(value: Any, *, directory: bool = False) -> Path:
    _need(
        type(value) is str and value and not any(ord(c) < 32 for c in value),
        "LOCAL_EDIT_CONFIGURATION_PATH_INVALID",
    )
    path = Path(value)
    _need(
        path.is_absolute()
        and ".." not in path.parts
        and not any(p.is_symlink() for p in (path, *path.parents))
        and (path.is_dir() if directory else path.is_file()),
        "LOCAL_EDIT_CONFIGURATION_PATH_INVALID",
    )
    return path


def _read_bytes(
    path: Path,
    expected: str | None = None,
    *,
    private: bool = False,
    maximum: int = 65536,
) -> bytes:
    _path(str(path))
    if expected is not None:
        _need(
            type(expected) is str and HASH.fullmatch(expected),
            "LOCAL_EDIT_CONFIGURATION_HASH_REQUIRED",
        )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            "LOCAL_EDIT_CONFIGURATION_INVALID",
        )
        _need(
            not private
            or (before.st_uid == os.getuid() and before.st_mode & 0o077 == 0),
            "LOCAL_EDIT_PRIVATE_CONFIG_REQUIRED",
        )
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())

    def identity(s: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)

    _need(
        identity(before) == identity(after) == identity(path.lstat())
        and len(raw) == before.st_size,
        "LOCAL_EDIT_CONFIGURATION_CHANGED",
    )
    _need(
        expected is None or hashlib.sha256(raw).hexdigest() == expected,
        "LOCAL_EDIT_CONFIGURATION_CHANGED",
    )

    return raw


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _need(key not in result, "LOCAL_EDIT_CONFIGURATION_INVALID")
        result[key] = value
    return result


def _read(
    path: Path, expected: str | None = None, *, private: bool = False
) -> dict[str, Any]:
    raw = _read_bytes(path, expected, private=private)
    value = json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise GradebookError("LOCAL_EDIT_CONFIGURATION_INVALID")
    return dict(value)


def _assignment_bindings(path: Path, expected: str) -> list[dict[str, Any]]:
    try:
        raw = _read_bytes(path, expected, maximum=2 * 1024 * 1024)
    except GradebookError as error:
        if str(error) == "LOCAL_EDIT_CONFIGURATION_CHANGED":
            raise GradebookError("LOCAL_EDIT_ASSIGNMENT_BINDINGS_CHANGED") from None
        raise
    value = json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise GradebookError("LOCAL_EDIT_ASSIGNMENT_BINDINGS_INVALID")
    return [dict(row) for row in value]


def _preservation(staging: dict[str, Any]) -> dict[str, Any] | None:
    keys = {"edit_preservation_path", "edit_preservation_sha256"}
    present = keys.intersection(staging)
    _need(not present or present == keys, "EXACT_EDIT_CONFIG_REQUIRED")
    if not present:
        return None
    return _read(
        _path(staging["edit_preservation_path"]),
        staging["edit_preservation_sha256"],
        private=True,
    )


def load_configuration(
    path: Path, expected_sha256: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Read pinned configuration and existing paths only; never open a DB."""
    try:
        config = _read(path, expected_sha256, private=True)
        unit1 = config.get("contract") in {UNIT1_CONTRACT, UNIT1_PROPOSAL_CONTRACT}
        proposal = config.get("contract") in {
            PROPOSAL_CONTRACT,
            UNIT1_PROPOSAL_CONTRACT,
        }
        fields = FIELDS - {"decision_id"} | {"result_id"} if proposal else FIELDS
        identity_key = "result_id" if proposal else "decision_id"
        _need(
            set(config) == (fields - {"source_root"} if unit1 else fields)
            and config["contract"]
            in {CONTRACT, UNIT1_CONTRACT, PROPOSAL_CONTRACT, UNIT1_PROPOSAL_CONTRACT},
            "LOCAL_EDIT_CONFIGURATION_INVALID",
        )
        _need(
            all(
                type(config[k]) is str and HASH.fullmatch(config[k])
                for k in (identity_key, "source_receipt_id", "staging_config_sha256")
            )
            and type(config["section"]) is str
            and config["section"].strip(),
            "LOCAL_EDIT_FIXED_SCOPE_REQUIRED",
        )
        for key in (
            ("identity_runtime_root",)
            if unit1
            else ("source_root", "identity_runtime_root")
        ):
            _path(config[key], directory=True)
        _path(config["shared_tool"])
        staging = _read(
            _path(config["staging_config_path"]),
            config["staging_config_sha256"],
            private=True,
        )
        _need(
            staging.get("course") in {"core", "advanced"}
            and staging.get("runtime_root") == config["identity_runtime_root"],
            "LOCAL_EDIT_EXISTING_CONFIG_MISMATCH",
        )
        for key in ("output_root", "runtime_root", "canvas_repo"):
            _path(staging[key], directory=True)
        for key in ("assignment_bindings_path", "pin_registry", "worker_config"):
            _path(staging[key])
        assignments = _path(staging["assignment_bindings_path"])
        _need(
            type(staging.get("assignment_bindings_sha256")) is str
            and HASH.fullmatch(staging["assignment_bindings_sha256"]),
            "LOCAL_EDIT_ASSIGNMENT_BINDINGS_CHANGED",
        )
        _assignment_bindings(assignments, staging["assignment_bindings_sha256"])
        _preservation(staging)
        binding = _read(
            Path(staging["canvas_repo"]) / "config/sdm-gradebook-workbooks.json"
        )[staging["course"]]
        _need(
            type(binding) is dict
            and binding.get("spreadsheet_id") == staging.get("spreadsheet_id"),
            "LOCAL_EDIT_EXISTING_CONFIG_MISMATCH",
        )
        worker = _read(Path(staging["worker_config"]), private=True)
        _path(worker["state_dir"], directory=True)
        return config, staging, binding
    except GradebookError:
        raise
    except Exception:
        raise GradebookError("LOCAL_EDIT_CONFIGURATION_INVALID") from None


def build_owner_factory(
    review: Any,
    source_intake: Any,
    canvas: GradebookClient,
    google: GoogleSheets,
    store: Store,
    journal: RefreshJournal,
    *,
    config_path: Path,
    expected_config_sha256: str,
    runtime_check: Callable[[], None] | None = None,
) -> Callable[[str, str], LocalGrAssEditOwner]:
    """Reuse already opened owners; never initialize a journal, intake or DB."""
    TeacherReview = importlib.import_module("localgrass.teacher_review").TeacherReview
    SourceIntake = importlib.import_module("localgrass.source_intake").SourceIntake
    AuthenticatedDecisionSource = importlib.import_module(
        "localgrass.teacher_edit_source"
    ).AuthenticatedDecisionSource

    frozen = load_configuration(config_path, expected_config_sha256)
    config, staging, binding = frozen
    unit1 = config["contract"] in {UNIT1_CONTRACT, UNIT1_PROPOSAL_CONTRACT}
    proposal = config["contract"] in {PROPOSAL_CONTRACT, UNIT1_PROPOSAL_CONTRACT}
    identity_key = "result_id" if proposal else "decision_id"
    connection_type = LocalGrAssEditConnection
    if unit1:
        AuthenticatedDecisionSource = importlib.import_module(
            "localgrass.teacher_edit_unit1"
        ).AuthenticatedUnit1DecisionSource
        _need(
            getattr(review.workflow, "identity_runtime_root", None)
            == Path(config["identity_runtime_root"]),
            "LOCAL_EDIT_IDENTITY_RUNTIME_CHANGED",
        )

    if proposal:
        module = importlib.import_module("localgrass.teacher_edit_proposal")
        AuthenticatedDecisionSource = (
            module.AuthenticatedUnit1ProposalSource
            if unit1
            else module.AuthenticatedProposalSource
        )
        connection_type = importlib.import_module(
            "canvas_mcp.gradebook.localgrass_proposal_edit"
        ).LocalGrAssProposalEditConnection

    _need(
        isinstance(review, TeacherReview)
        and (
            (source_intake is None and callable(review.workflow.paper_source_reader))
            if unit1
            else isinstance(source_intake, SourceIntake)
            and source_intake.registry is review.registry
        )
        and isinstance(canvas, GradebookClient)
        and isinstance(google, GoogleSheets)
        and isinstance(store, Store)
        and isinstance(journal, RefreshJournal),
        "LOCAL_EDIT_APP_OWNERS_REQUIRED",
    )
    worker = _read(Path(staging["worker_config"]), private=True)
    _need(
        store.root == Path(worker["state_dir"])
        and journal.root.parent == store.root
        and journal.path.is_file()
        and journal.workbook_id == google.workbook_id == binding["spreadsheet_id"],
        "LOCAL_EDIT_APP_OWNER_MISMATCH",
    )

    def check_runtime() -> None:
        try:
            _need(callable(runtime_check), "LOCAL_EDIT_RUNTIME_CHECK_REQUIRED")
            _need(
                runtime_check is not None and runtime_check() is None,
                "LOCAL_EDIT_IMMUTABLE_RUNTIME_HELD",
            )
        except Exception:
            raise GradebookError("LOCAL_EDIT_IMMUTABLE_RUNTIME_HELD") from None

    def owner_factory(token: str, csrf: str) -> LocalGrAssEditOwner:
        try:
            check_runtime()
            _need(
                load_configuration(config_path, expected_config_sha256) == frozen,
                "LOCAL_EDIT_CONFIGURATION_CHANGED",
            )
            review.check_csrf(token, csrf)
            review.actor_for_session(token)
            # Check existing exact records before constructing any composition.
            # Missing intake schema/case is an admission hold, never initialization.
            if not unit1:
                source_intake._schema()
                source_intake._stored(config["source_receipt_id"])
            if proposal:
                row = review.registry.connection.execute(
                    "SELECT proposal_id FROM workflow_proposals WHERE proposal_id=?",
                    ("proposal-" + config["result_id"],),
                ).fetchone()
            else:
                row = review.registry.connection.execute(
                    "SELECT decision_id FROM workflow_teacher_acceptances WHERE decision_id=?",
                    (config["decision_id"],),
                ).fetchone()
            _need(row is not None, "LOCAL_EDIT_REAL_CASE_NOT_ADMITTED")

            # The optional domain dependency has no installed type stub. Runtime
            # isinstance checks still use its actual concrete source authority.
            class GuardedDecisionSource(AuthenticatedDecisionSource):  # type: ignore[misc,valid-type]
                def read(self) -> dict[str, Any]:
                    check_runtime()
                    snapshot: dict[str, Any] = super().read()
                    check_runtime()
                    return snapshot

            source_args = {
                "source_receipt_id": config["source_receipt_id"],
                identity_key: config[identity_key],
                "identity_runtime_root": Path(config["identity_runtime_root"]),
            }
            if not unit1:
                source_args.update(
                    source_intake=source_intake, source_root=Path(config["source_root"])
                )
            source = GuardedDecisionSource(review, token, csrf, **source_args)
            connection = connection_type(
                source,
                store,
                assignment_bindings_path=Path(staging["assignment_bindings_path"]),
                expected_assignment_bindings_sha256=staging[
                    "assignment_bindings_sha256"
                ],
                section=config["section"],
                registry_path=Path(staging["pin_registry"]),
                shared_tool=Path(config["shared_tool"]),
                preservation=_preservation(staging),
            )
            return LocalGrAssEditOwner(
                connection,
                canvas,
                google,
                journal,
                staging_config_path=Path(config["staging_config_path"]),
                expected_staging_config_sha256=config["staging_config_sha256"],
                binding=binding,
            )
        except Exception:
            raise GradebookError("LOCAL_EDIT_CASE_OR_CONFIG_HELD") from None

    return owner_factory


def build_application(
    review: Any,
    source_intake: Any,
    canvas: GradebookClient,
    google: GoogleSheets,
    store: Store,
    journal: RefreshJournal,
    *,
    config_path: Path,
    expected_config_sha256: str,
    enabled: bool = False,
    runtime_check: Callable[[], None] | None = None,
) -> Any:
    """Compose the existing review server extension; explicit staging gate off."""
    LocalEditApplication = importlib.import_module(
        "localgrass.teacher_edit_application"
    ).LocalEditApplication
    _need(not enabled or callable(runtime_check), "LOCAL_EDIT_RUNTIME_CHECK_REQUIRED")

    config, _, _ = load_configuration(config_path, expected_config_sha256)
    _need(
        config["contract"] not in {PROPOSAL_CONTRACT, UNIT1_PROPOSAL_CONTRACT},
        "PROPOSAL_CONFIG_REQUIRES_OWNER_WORKFLOW",
    )
    factory = build_owner_factory(
        review,
        source_intake,
        canvas,
        google,
        store,
        journal,
        config_path=config_path,
        expected_config_sha256=expected_config_sha256,
        runtime_check=runtime_check,
    )
    return LocalEditApplication(
        review,
        factory,
        decision_id=config["decision_id"],
        source_receipt_id=config["source_receipt_id"],
        section=config["section"],
        enabled=enabled,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        load_configuration(args.config, args.config_sha256)
        print(
            json.dumps(
                {
                    "status": "CONFIGURATION_VERIFIED",
                    "staging_enabled": False,
                    "real_case_checked": False,
                    "database_opens": 0,
                    "network_calls": 0,
                    "Canvas_writes": 0,
                    "schemas_created": 0,
                }
            )
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "status": "HELD",
                    "reason": "LOCAL_EDIT_CONFIGURATION_HELD",
                    "network_calls": 0,
                    "Canvas_writes": 0,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
