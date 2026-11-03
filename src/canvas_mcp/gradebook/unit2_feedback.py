"""Offline driver delegating to the single pinned JavaScript formatter.

The caller owns independent source/header qualification. Equality with a supplied
trusted snapshot is a drift check, not authentication. Nothing here accepts a
teacher decision, writes an audit record, or authorizes delivery.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .model import GradebookError

_DRIVER = """
import fs from 'node:fs';
const p=JSON.parse(fs.readFileSync(0,'utf8'));
const m=await import('data:text/javascript;base64,'+p.module);
if(typeof m.formatFeedback!=='function') throw new Error('MISSING_PINNED_EXPORT');
const r=m.formatFeedback(p.input,p.trusted);
if(r && typeof r.then==='function') throw new Error('ASYNC_FORMATTER');
process.stdout.write(JSON.stringify(r));
"""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise GradebookError(message)


def _json_bytes(value: Any) -> bytes:
    def portable(v: Any, active: set[int]) -> None:
        if v is None or type(v) in (str, int, float, bool):
            return
        _need(
            type(v) in (list, dict) and id(v) not in active, "Portable JSON required."
        )
        active.add(id(v))
        if type(v) is dict:
            _need(all(type(k) is str for k in v), "Text JSON keys required.")
            for w in v.values():
                portable(w, active)
        else:
            for w in v:
                portable(w, active)
        active.remove(id(v))

    try:
        portable(value, set())
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise GradebookError("Portable JSON required.") from exc


def _formatter_environment(
    platform: str, inherited: Mapping[str, str]
) -> dict[str, str]:
    """Keep credentials and Node preload/options out of the offline process."""
    env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"}
    if platform == "win32":
        # Windows needs its system directories for Node's Winsock/crypto
        # startup, as in the maintained code-execution runtime probe. The
        # executable is absolute; host PATH and all Node options stay excluded.
        for key in ("SYSTEMROOT", "WINDIR"):
            value = inherited.get(key)
            if value is not None:
                env[key] = value
    return env


def derive_projection(
    formatter_input: dict[str, Any],
    trusted_projection: dict[str, Any],
    *,
    formatter_path: str | Path,
    formatter_sha256: str,
    node_path: str | Path,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Execute exactly the caller-pinned JS bytes, with no inherited credentials.

    Paths and hash are explicit; no installation, configuration or discovery.
    The reviewed JS owns derived MC arithmetic; the concise renderer does not.
    """
    _need(
        type(formatter_input) is dict and type(trusted_projection) is dict,
        "Independent projection objects required.",
    )
    _need(
        _json_bytes(formatter_input) == _json_bytes(trusted_projection),
        "Trusted projection changed.",
    )
    _need(
        type(formatter_sha256) is str
        and re.fullmatch(r"[a-f0-9]{64}", formatter_sha256) is not None,
        "Exact formatter hash required.",
    )
    script, node = Path(formatter_path), Path(node_path)
    _need(
        script.is_absolute() and node.is_absolute(), "Absolute runtime paths required."
    )
    _need(
        type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 5,
        "Formatter timeout must be at most five seconds.",
    )
    try:
        with script.open("rb") as stream:
            source = stream.read(1_000_001)
        _need(
            len(source) <= 1_000_000
            and hashlib.sha256(source).hexdigest() == formatter_sha256,
            "Formatter hash changed.",
        )
        payload = _json_bytes(
            {
                "module": base64.b64encode(source).decode("ascii"),
                "input": formatter_input,
                "trusted": trusted_projection,
            }
        )
        _need(len(payload) <= 3_000_000, "Formatter input exceeds bound.")
        result = subprocess.run(
            [str(node), "--input-type=module", "-e", _DRIVER],
            input=payload,
            capture_output=True,
            shell=False,
            timeout=timeout_seconds,
            check=False,
            env=_formatter_environment(sys.platform, os.environ),
        )
        _need(
            result.returncode == 0 and len(result.stdout) <= 2_000_000,
            "Pinned formatter failed safely.",
        )
        output: dict[str, Any] = json.loads(result.stdout)
        _need(type(output) is dict, "Pinned formatter returned an invalid projection.")
        _json_bytes(output)
        return output
    except GradebookError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
        raise GradebookError("Pinned formatter unavailable or failed safely.") from None
