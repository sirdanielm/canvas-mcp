"""File-backed, cached-only Unit 2 advisory qualification; no staging or delivery.

The owning GrAss adapter and formatter validate saved native records. This module
neither scores a source nor trusts a prepared receipt as its own source authority.
Existing-assignment mapping is deliberately unsupported: qualified sources still
return a private held preview, never a publisher body or an EDIT-cell request.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from copy import deepcopy
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .localgrass_application import _read_bytes
from .model import GradebookError, digest

_MAXIMUM = 8 * 1024 * 1024
_DRIVER = r"""
import fs from 'node:fs';
const p=JSON.parse(fs.readFileSync(0,'utf8'));
const dataURL=raw=>'data:text/javascript;base64,'+Buffer.from(raw).toString('base64');
const formatter=Buffer.from(p.formatter,'base64'),fURL=dataURL(formatter);
function rewrite(source,name,url){
 const pattern=new RegExp("(['\"])\\.\\/"+name.replaceAll('.','\\.')+"\\1",'g');
 if([...source.matchAll(pattern)].length!==1)throw Error('EXACT_SINGLE_IMPORT_REQUIRED');
 return source.replace(pattern,JSON.stringify(url));
}
const adapter=rewrite(Buffer.from(p.adapter,'base64').toString('utf8'),'compact_feedback.mjs',fURL);
let preparer=Buffer.from(p.preparer,'base64').toString('utf8');
preparer=rewrite(preparer,'native_compact_input.mjs',dataURL(adapter));
preparer=rewrite(preparer,'compact_feedback.mjs',fURL);
const owner=await import(dataURL(preparer));
const prepared=owner.prepareCompactFeedback(p.bundle,{reviewSnapshot:p.review,formatterBytes:formatter,
 contractBytes:Buffer.from(p.contract_bytes,'base64')});
process.stdout.write(JSON.stringify({input:prepared.input,output:prepared.output,receipt:prepared.receipt,
 input_bytes:prepared.inputBytes.toString('base64'),output_bytes:prepared.outputBytes.toString('base64'),
 receipt_bytes:Buffer.from(JSON.stringify(prepared.receipt,null,2)+'\n').toString('base64')}));
"""


@dataclass(frozen=True)
class FilePin:
    path: Path
    sha256: str
    byte_count: int | None = None


@dataclass(frozen=True)
class PreparedFiles:
    input: FilePin
    output: FilePin
    receipt: FilePin


@dataclass(frozen=True)
class NativeFiles:
    head: FilePin
    packet: FilePin
    reading: FilePin
    reading_manifest: FilePin
    result: FilePin
    policy: FilePin
    academic: FilePin
    feedback: FilePin
    review_snapshot: FilePin | None = None
    feedback_reference: FilePin | None = None
    short_corrections: FilePin | None = None


@dataclass(frozen=True)
class CanonicalFiles:
    native_adapter: FilePin
    formatter: FilePin
    contract: FilePin
    node_path: Path
    preparer: FilePin | None = None


def _need(value: bool, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _json(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            _need(key not in result, "UNIT2_CACHED_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise GradebookError("UNIT2_CACHED_NONFINITE_JSON")

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
        )
        _need(type(value) is dict, "UNIT2_CACHED_OBJECT_REQUIRED")
        # This also rejects overflowed exponent values such as 1e999.
        json.dumps(value, allow_nan=False).encode("utf-8")
        return dict(value)
    except GradebookError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise GradebookError("UNIT2_CACHED_INVALID_JSON") from None


def _read(pin: FilePin, *, private: bool) -> bytes:
    _need(
        type(pin) is FilePin and isinstance(pin.path, Path),
        "UNIT2_CACHED_FILE_PIN_REQUIRED",
    )
    _need(
        type(pin.sha256) is str
        and re.fullmatch(r"[a-f0-9]{64}", pin.sha256) is not None,
        "UNIT2_CACHED_FILE_PIN_REQUIRED",
    )
    _need(
        pin.byte_count is None
        or type(pin.byte_count) is int
        and 0 < pin.byte_count <= _MAXIMUM,
        "UNIT2_CACHED_FILE_SIZE_REQUIRED",
    )
    try:
        raw = _read_bytes(pin.path, pin.sha256, private=private, maximum=_MAXIMUM)
    except Exception:
        raise GradebookError("UNIT2_CACHED_FILE_CHANGED_OR_UNSAFE") from None
    _need(
        pin.byte_count is None or len(raw) == pin.byte_count,
        "UNIT2_CACHED_FILE_SIZE_CHANGED",
    )
    return raw


def qualify_cached_review(
    prepared: PreparedFiles,
    native: NativeFiles,
    code: CanonicalFiles,
    *,
    target: Any = None,
) -> dict[str, Any]:
    """Rebuild canonical input/output/receipt from pinned native files, read-only.

    Non-None targets are not admitted by this interface. A successful source
    check always remains HELD for an independently reviewed assignment mapping.
    No caller callback can substitute for file-backed native validation.
    """
    _need(target is None, "UNIT2_CACHED_TARGET_UNSUPPORTED")
    _need(
        type(prepared) is PreparedFiles
        and type(native) is NativeFiles
        and type(code) is CanonicalFiles,
        "UNIT2_CACHED_TYPED_FILES_REQUIRED",
    )
    readset: list[tuple[FilePin, bool, bytes]] = []

    def read(pin: FilePin, private: bool = True) -> bytes:
        raw = _read(pin, private=private)
        readset.append((pin, private, raw))
        return raw

    prepared_raw = {f.name: read(getattr(prepared, f.name)) for f in fields(prepared)}
    saved = {name: _json(raw) for name, raw in prepared_raw.items()}
    source_raw = {
        f.name: read(getattr(native, f.name), False)
        for f in fields(native)
        if f.name not in {"review_snapshot", "feedback_reference", "short_corrections"}
    }
    source = {
        name: _json(raw) for name, raw in source_raw.items() if name != "feedback"
    }
    review = (
        _json(read(native.review_snapshot, False))
        if native.review_snapshot is not None
        else None
    )
    _need(
        saved["receipt"].get("binding_scope") != "ITEM" or review is not None,
        "UNIT2_CACHED_ITEM_BINDING_REQUIRED",
    )
    head, packet = source["head"], source["packet"]
    _need(
        head.get("packet_id", head.get("packet_key")) == packet.get("packet_id"),
        "UNIT2_CACHED_CURRENT_PACKET_CHANGED",
    )
    current = {
        "packet_id": packet.get("packet_id"),
        "reading_key": head.get("reading_key"),
        "result_key": head.get("result_key"),
    }
    try:
        bundle: dict[str, Any] = {
            name + "_json": source_raw[name].decode("utf-8")
            for name in (
                "packet",
                "reading",
                "reading_manifest",
                "result",
                "policy",
                "academic",
            )
        }
        bundle.update(
            current=current, feedback_body=source_raw["feedback"].decode("utf-8")
        )
    except UnicodeError:
        raise GradebookError("UNIT2_CACHED_INVALID_UTF8") from None
    adapter, formatter, contract_raw = (
        read(code.native_adapter, False),
        read(code.formatter, False),
        read(code.contract, False),
    )
    _json(contract_raw)
    _need(code.preparer is not None, "UNIT2_CACHED_PREPARER_PIN_REQUIRED")
    assert code.preparer is not None
    preparer = read(code.preparer, False)
    for name in ("feedback_reference", "short_corrections"):
        reference = getattr(native, name)
        if reference is not None:
            bundle[name] = _json(read(reference, False))
    _need(
        isinstance(code.node_path, Path)
        and code.node_path.is_absolute()
        and code.node_path.is_file()
        and code.node_path.resolve() == code.node_path
        and not code.node_path.is_symlink(),
        "UNIT2_CACHED_DIRECT_NODE_REQUIRED",
    )
    payload = {
        "adapter": base64.b64encode(adapter).decode("ascii"),
        "formatter": base64.b64encode(formatter).decode("ascii"),
        "contract_bytes": base64.b64encode(contract_raw).decode("ascii"),
        "preparer": base64.b64encode(preparer).decode("ascii"),
        "bundle": bundle,
        "review": review,
    }
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
        _need(len(encoded) <= 64 * 1024 * 1024, "UNIT2_CACHED_INPUT_TOO_LARGE")
        completed = subprocess.run(
            [str(code.node_path), "--input-type=module", "-e", _DRIVER],
            input=encoded,
            capture_output=True,
            shell=False,
            check=False,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        )
        _need(
            completed.returncode == 0 and len(completed.stdout) <= 32 * 1024 * 1024,
            "UNIT2_CACHED_NATIVE_QUALIFICATION_HELD",
        )
        regenerated = _json(completed.stdout)
        for name in ("input", "output", "receipt"):
            _need(
                saved[name] == regenerated[name]
                and prepared_raw[name]
                == base64.b64decode(regenerated[name + "_bytes"], validate=True),
                "UNIT2_CACHED_PREPARATION_CHANGED",
            )
    except GradebookError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        raise GradebookError("UNIT2_CACHED_NATIVE_QUALIFICATION_HELD") from None
    # Recheck every source, preparation and code byte after external computation.
    for pin, private, before in readset:
        _need(_read(pin, private=private) == before, "UNIT2_CACHED_READSET_CHANGED")
    output = saved["output"]
    _need(
        output.get("whole_final_numeric") is None
        and output.get("publication_allowed") is False
        and output.get("staging_allowed") is False,
        "UNIT2_CACHED_OUTPUT_AUTHORITY_INVALID",
    )
    mc_status = output.get("status")
    _need(
        mc_status in ("MC_COMPLETE", "MC_PARTIAL_HOLD"),
        "UNIT2_CACHED_MC_STATUS_REQUIRED",
    )
    plan = {
        "contract": "UNIT2_CACHED_PRIVATE_REVIEW_V1",
        "state": (
            "HELD_MC_SOURCE_REVIEW_REQUIRED"
            if mc_status == "MC_PARTIAL_HOLD"
            else "HELD_ASSIGNMENT_BINDING_REQUIRED"
        ),
        "source_qualified": True,
        "qualification_scope": "NATIVE_CACHED_BINDINGS_ONLY",
        "cached_only": True,
        "live_freshness_claim": False,
        "original_source_media_read": False,
        "key_pdf_bytes_verified": False,
        "component_status": mc_status,
        "whole_final_numeric": None,
        "private_preview": deepcopy(output),
        "source_binding": deepcopy(output["source_binding"]),
        "native_holds": deepcopy(source["result"].get("holds", [])),
        "prepared_receipt": deepcopy(saved["receipt"]),
        "readset": [
            {"path": str(pin.path), "sha256": pin.sha256, "bytes": len(raw)}
            for pin, _private, raw in readset
        ],
        "target": None,
        "requests": [],
        "publisher_category_admitted": False,
        "teacher_accepted": False,
        "content_approved": False,
        "source_approved": False,
        "publication_allowed": False,
        "score_delivery_authorized": False,
        "comment_delivery_authorized": False,
        "canonical_import_allowed": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
        "store_writes": 0,
    }
    plan["plan_id"] = digest(plan)
    return plan
