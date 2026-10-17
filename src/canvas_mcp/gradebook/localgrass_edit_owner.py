"""Application composition for authenticated local EDIT staging, off by default.

Reuse existing configured clients, private staging history and workbook lock.
This module creates no clients, credentials, decisions, queue or publication
permission. An installed application must supply its authenticated connection.
"""

from __future__ import annotations

import copy
import importlib
from pathlib import Path
from typing import Any

from .client import GradebookClient, GradebookError
from .get_only_refresh import validate_get_workbook
from .google import GoogleSheets
from .localgrass_edit_execution import execute_local_edit_once
from .localgrass_teacher_edit import LocalGrAssEditConnection
from .worker import RefreshJournal


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


class LocalGrAssEditOwner:
    """Bind the existing local owner configuration to prepare/execute/reconcile.

    Configuration and objects are trusted application inputs, never request JSON.
    The existing participation configuration pins the shared history root. The
    existing refresh journal excludes GET/full-refresh writers during the whole
    operation. A concurrent browser editor still requires an idle checkpoint;
    Google Sheets offers no atomic compare-and-swap for this native cell batch.
    """

    def __init__(
        self,
        connection: LocalGrAssEditConnection,
        canvas: GradebookClient,
        google: GoogleSheets,
        journal: RefreshJournal,
        *,
        staging_config_path: Path,
        expected_staging_config_sha256: str,
        binding: dict[str, Any],
    ) -> None:
        _need(
            isinstance(connection, LocalGrAssEditConnection)
            and isinstance(canvas, GradebookClient)
            and isinstance(google, GoogleSheets)
            and isinstance(journal, RefreshJournal),
            "EXISTING_LOCAL_EDIT_OWNERS_REQUIRED",
        )
        _need(
            isinstance(staging_config_path, Path) and staging_config_path.is_absolute(),
            "EXISTING_STAGING_CONFIG_REQUIRED",
        )
        self.connection, self.canvas, self.google, self.journal = (
            connection,
            canvas,
            google,
            journal,
        )
        self.config_path = staging_config_path
        self.config_sha256 = expected_staging_config_sha256
        self.binding = copy.deepcopy(binding)
        self._pin_module = importlib.import_module("localgrass.teacher_edit_identity")
        self._pin_defaults = importlib.import_module("localgrass.student_pin")
        self.config = self._configuration()
        self.output_root = connection.files.local_path(self.config["output_root"])
        _need(self.output_root.is_dir(), "EXISTING_STAGING_HISTORY_REQUIRED")
        self.runtime_root = connection.files.local_path(self.config["runtime_root"])
        _need(
            journal.root.parent.resolve() == connection.store.root
            and journal.workbook_id == google.workbook_id == binding["spreadsheet_id"],
            "EXISTING_WORKBOOK_OWNER_MISMATCH",
        )

    def _configuration(self) -> dict[str, Any]:
        files = self.connection.files
        _need(
            files.file_sha(self.config_path) == self.config_sha256,
            "EXISTING_STAGING_CONFIG_CHANGED",
        )
        config: dict[str, Any] = files.load(self.config_path)
        _need(
            files.file_sha(self.config_path) == self.config_sha256
            and type(config) is dict
            and config.get("course") in {"core", "advanced"}
            and config.get("spreadsheet_id") == self.binding["spreadsheet_id"]
            and config.get("assignment_bindings_sha256")
            == self.connection.assignment_sha256
            and files.local_path(config["assignment_bindings_path"])
            == files.local_path(self.connection.assignment_path)
            and files.local_path(
                config.get("pin_registry", self._pin_defaults.DEFAULT_REGISTRY)
            )
            == files.local_path(self.connection.registry_path),
            "EXISTING_STAGING_CONFIG_CHANGED",
        )
        bindings_path = (
            files.local_path(config["canvas_repo"])
            / "config/sdm-gradebook-workbooks.json"
        )
        _need(
            files.load(bindings_path).get(config["course"]) == self.binding,
            "REGISTERED_WORKBOOK_BINDING_CHANGED",
        )
        worker_config = files.load(files.local_path(config["worker_config"]))
        _need(
            type(worker_config) is dict
            and files.local_path(worker_config["state_dir"])
            == self.connection.store.root,
            "EXISTING_WORKER_STATE_CHANGED",
        )
        return config

    def _check_owner(self, *, reconciliation: bool = False) -> None:
        _need(self._configuration() == self.config, "EXISTING_STAGING_CONFIG_CHANGED")
        _need(
            self.journal.root.parent.resolve() == self.connection.store.root
            and self.journal.workbook_id
            == self.google.workbook_id
            == self.binding["spreadsheet_id"],
            "EXISTING_WORKBOOK_OWNER_MISMATCH",
        )
        _need(
            reconciliation or not self.journal.unresolved(),
            "UNRESOLVED_WORKBOOK_REFRESH_HISTORY",
        )

    async def _context(self) -> dict[str, Any]:
        self._configuration()
        current = await self.canvas.snapshot(str(self.binding["course_id"]))
        _need(
            current.get("origin") == self.canvas.origin
            and current.get("course_id") == str(self.binding["course_id"]),
            "CURRENT_CANVAS_OWNER_CHANGED",
        )
        pins = self._pin_module.canonical_pin_binding(
            self.connection.registry_path, self.runtime_root
        )
        # Last network read before preflight: native access/token and the full
        # destination preimage are checked together by the existing transport.
        raw = await self.google.read_workbook()
        return {"raw": raw, "current": current, "pin_binding": pins}

    async def prepare(self) -> dict[str, Any]:
        """Read through existing owners and retain one exact immutable plan."""
        with self.journal.exclusive():
            self._check_owner()
            context = await self._context()
            views = validate_get_workbook(context["raw"], {"bound": self.binding})[
                "bound"
            ]
            baseline = self.connection.store.load("snapshot", views["_Sync"]["B2"])
            _need(
                baseline.get("origin") == self.canvas.origin
                and baseline.get("course_id") == str(self.binding["course_id"]),
                "TRUSTED_EDIT_BASELINE_CHANGED",
            )
            plan = self.connection.prepare(
                **context, baseline=baseline, binding=self.binding
            )
            plan_id, _ = self.connection.store.save("review", plan)
            return {
                "status": "PREPARED_LOCAL_EDIT_ONLY",
                "plan_id": plan_id,
                "canvas_writes": 0,
                "sheets_write_requests": 0,
                "publication_allowed": False,
            }

    async def execute(
        self,
        plan_id: str,
        *,
        enabled: bool = False,
        reconcile_only: bool = False,
        max_seconds: float = 120,
    ) -> dict[str, Any]:
        """Execute only an existing retained plan; defaults perform no I/O.

        Human authorization and an idle workbook remain application controls.
        Reconciliation can inspect prior sends despite an unresolved refresh,
        but never invokes a native writer or releases either owner's history.
        """
        _need(
            type(enabled) is bool and type(reconcile_only) is bool,
            "EXPLICIT_LOCAL_EXECUTION_MODE",
        )
        if not enabled and not reconcile_only:
            return {
                "status": "LOCAL_EDIT_WRITE_DISABLED",
                "canvas_writes": 0,
                "sheets_write_requests": 0,
                "retry_writes": False,
                "publication_allowed": False,
            }
        with self.journal.exclusive():
            plan = self.connection.store.load("review", plan_id)
            _need(
                plan.get("binding") == self.binding, "RETAINED_WORKBOOK_BINDING_CHANGED"
            )
            # Any prior attempt enters native readback only. Reconciliation
            # must remain available when Canvas, source files or teacher login
            # are unavailable; they are required for new sends, not readback.
            retained = any((self.output_root / plan_id).glob("receipt-*.json"))
            readback_only = reconcile_only or retained
            self._check_owner(reconciliation=readback_only)
            send_started = False

            async def read() -> dict[str, Any]:
                if readback_only or send_started:
                    return {"raw": await self.google.read_workbook()}
                return await self._context()

            async def write(spreadsheet: str, requests: list[dict[str, Any]]) -> Any:
                nonlocal send_started
                self._check_owner()
                _need(
                    spreadsheet == self.google.workbook_id,
                    "FIXED_NATIVE_TARGET_CHANGED",
                )
                # Do not call batch(): it adds a metadata read/authentication
                # refresh after the executor's durable SENDING checkpoint.
                send_started = True
                return await self.google.send_preflighted_batch(requests)

            return await execute_local_edit_once(
                self.connection,
                plan,
                expected_plan_sha256=plan_id,
                output_root=self.output_root,
                read_context=read,
                write_requests=write,
                enabled=enabled,
                reconcile_only=readback_only,
                max_seconds=max_seconds,
            )
