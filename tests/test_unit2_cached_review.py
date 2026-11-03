"""Only fictional files; optional owning-JS integration uses explicit code paths."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from canvas_mcp.gradebook import unit2_cached_review as cached
from canvas_mcp.gradebook.model import GradebookError

_FIXTURE_DRIVER = r"""
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';
import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';
const dir=process.argv[1],held=process.argv[2]==='held',itemScope=process.argv[3]==='item';
const fixturePath=path.resolve(dir,'../../tests/unit2_native_compact_input.test.js');
const source=fs.readFileSync(fixturePath,'utf8');
const context=vm.createContext({require:createRequire(fixturePath),structuredClone,Buffer});
vm.runInContext(source.slice(0,source.indexOf('async function modules()'))+'\nglobalThis.build=bundle;globalThis.records=fixture;',context);
const records=context.records();
if(held){records.result.items[0].earned_points=null;records.result.known_weighted_earned='70';
 records.result.holds.push({item_id:'MC01',reason:'FICTIONAL_SOURCE_HOLD'});}
const bundle=JSON.parse(JSON.stringify(context.build(records)));
if(process.argv[4]!=='aux')delete bundle.feedback_reference;
else bundle.short_corrections={'FRQ01/a':{text:'Fictional explicit correction',authority_reference:'FICTIONAL_OWNER'}};
const prep=await import(pathToFileURL(path.join(dir,'prepare_compact_feedback.mjs')));
let review=null;
if(itemScope){const reading=JSON.parse(bundle.reading_json),item=reading.items[0],packet=JSON.parse(bundle.packet_json),result=JSON.parse(bundle.result_json);
 review={binding:{...bundle.current,source_sha256:packet.source_sha256,form_id:packet.form_id,attempt:'R1',item_id:item.item_id,
 policy_sha256:result.policy_sha256,before_item_sha256:prep.digest(prep.canonical(item))},option_marks_before:item.option_marks,current_item:item};}
const out=prep.prepareCompactFeedback(bundle,{reviewSnapshot:review,formatterBytes:fs.readFileSync(path.join(dir,'compact_feedback.mjs')),
 contractBytes:fs.readFileSync(path.join(dir,'compact_feedback_contract.json'))});
process.stdout.write(JSON.stringify({bundle,review,input:out.inputBytes.toString('base64'),output:out.outputBytes.toString('base64'),receipt:Buffer.from(JSON.stringify(out.receipt,null,2)+'\n').toString('base64')}));
"""


def pin(path: Path, raw: bytes) -> cached.FilePin:
    path.write_bytes(raw)
    path.chmod(0o600)
    return cached.FilePin(path, hashlib.sha256(raw).hexdigest(), len(raw))


@pytest.fixture
def canonical_code() -> tuple[Path, Path]:
    location = os.environ.get("UNIT2_CANONICAL_SOURCE_DIR")
    if not location:
        pytest.skip("Owning canonical code directory is explicitly required")
    node = os.environ.get("UNIT2_NODE_PATH") or shutil.which("node")
    if not node:
        pytest.skip("Explicit Node runtime is unavailable")
    return Path(location).resolve(), Path(node).resolve()


def fixture_files(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
    *,
    held: bool = False,
    item: bool = False,
    auxiliary: bool = False,
) -> tuple[cached.PreparedFiles, cached.NativeFiles, cached.CanonicalFiles]:
    import base64

    directory, node = canonical_code
    response = subprocess.run(
        [
            str(node),
            "--input-type=module",
            "-e",
            _FIXTURE_DRIVER,
            str(directory),
            "held" if held else "clear",
            "item" if item else "packet",
            "aux" if auxiliary else "none",
        ],
        capture_output=True,
        check=True,
        timeout=5,
    )
    fixture: dict[str, Any] = json.loads(response.stdout)
    prepared = cached.PreparedFiles(
        **{
            name: pin(tmp_path / (name + ".json"), base64.b64decode(fixture[name]))
            for name in ("input", "output", "receipt")
        }
    )
    bundle = fixture["bundle"]
    source_pins = {
        name: pin(
            tmp_path / ("native-" + name + ".json"), bundle[name + "_json"].encode()
        )
        for name in (
            "packet",
            "reading",
            "reading_manifest",
            "result",
            "policy",
            "academic",
        )
    }
    source_pins["head"] = pin(
        tmp_path / "head.json", json.dumps(bundle["current"]).encode()
    )
    source_pins["feedback"] = pin(
        tmp_path / "feedback.txt", bundle["feedback_body"].encode()
    )
    for name in ("feedback_reference", "short_corrections"):
        if name in bundle:
            source_pins[name] = pin(
                tmp_path / (name + ".json"), json.dumps(bundle[name]).encode()
            )
    if fixture["review"] is not None:
        source_pins["review_snapshot"] = pin(
            tmp_path / "review.json", json.dumps(fixture["review"]).encode()
        )
    native = cached.NativeFiles(**source_pins)

    def source_pin(name: str) -> cached.FilePin:
        path = directory / name
        return cached.FilePin(
            path, hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size
        )

    code = cached.CanonicalFiles(
        source_pin("native_compact_input.mjs"),
        source_pin("compact_feedback.mjs"),
        source_pin("compact_feedback_contract.json"),
        node,
        source_pin("prepare_compact_feedback.mjs"),
    )
    return prepared, native, code


def test_qualifies_actual_canonical_replay_but_missing_target_holds(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
) -> None:
    prepared, native, code = fixture_files(tmp_path, canonical_code)
    result = cached.qualify_cached_review(prepared, native, code)
    assert result["state"] == "HELD_ASSIGNMENT_BINDING_REQUIRED"
    assert result["qualification_scope"] == "NATIVE_CACHED_BINDINGS_ONLY"
    assert (
        result["source_qualified"] is True and result["live_freshness_claim"] is False
    )
    assert result["private_preview"] == json.loads(prepared.output.path.read_bytes())
    assert result["private_preview"]["source_binding"] == result["source_binding"]
    assert result["source_binding"]["key_pdf_bytes_verified"] is False
    assert result["requests"] == [] and "comment_body" not in result
    assert (
        result["whole_final_numeric"] is None
        and result["publisher_category_admitted"] is False
    )


def test_held_native_mc_is_not_awarded_zero(
    tmp_path: Path, canonical_code: tuple[Path, Path]
) -> None:
    args = fixture_files(tmp_path, canonical_code, held=True)
    result = cached.qualify_cached_review(*args)
    assert result["state"] == "HELD_MC_SOURCE_REVIEW_REQUIRED"
    assert result["private_preview"]["items"][0]["earned_points"] is None
    assert result["private_preview"]["items"][0]["deduction"] == "PENDING"
    assert result["native_holds"] and "comment_body" not in result


def test_item_scope_requires_independently_pinned_snapshot(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
) -> None:
    prepared, native, code = fixture_files(tmp_path, canonical_code, item=True)
    with pytest.raises(GradebookError, match="^UNIT2_CACHED_ITEM_BINDING_REQUIRED$"):
        cached.qualify_cached_review(
            prepared, replace(native, review_snapshot=None), code
        )
    assert (
        cached.qualify_cached_review(prepared, native, code)["source_qualified"] is True
    )


def test_changed_prepared_output_even_with_fresh_file_pin_rejects(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
) -> None:
    prepared, native, code = fixture_files(tmp_path, canonical_code)
    output = json.loads(prepared.output.path.read_bytes())
    output["known_earned"] = "50"
    prepared = replace(
        prepared, output=pin(prepared.output.path, json.dumps(output).encode())
    )
    with pytest.raises(GradebookError, match="PREPARATION_CHANGED"):
        cached.qualify_cached_review(prepared, native, code)


def test_stale_current_head_with_fresh_file_pin_rejects(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
) -> None:
    prepared, native, code = fixture_files(tmp_path, canonical_code)
    head = json.loads(native.head.path.read_bytes())
    head["reading_key"] = "a" * 64
    native = replace(native, head=pin(native.head.path, json.dumps(head).encode()))
    with pytest.raises(GradebookError, match="QUALIFICATION_HELD"):
        cached.qualify_cached_review(prepared, native, code)


def test_full_readset_is_rechecked_after_node(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, native, code = fixture_files(tmp_path, canonical_code)
    actual = cached.subprocess.run

    def racing(*args: Any, **kwargs: Any) -> Any:
        result = actual(*args, **kwargs)
        native.head.path.write_bytes(b"{}")
        return result

    monkeypatch.setattr(cached.subprocess, "run", racing)
    with pytest.raises(GradebookError, match="CHANGED_OR_UNSAFE"):
        cached.qualify_cached_review(prepared, native, code)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":1e999}'])
def test_strict_json(raw: bytes) -> None:
    with pytest.raises(GradebookError):
        cached._json(raw)


def test_targets_are_explicitly_unsupported() -> None:
    with pytest.raises(GradebookError, match="^UNIT2_CACHED_TARGET_UNSUPPORTED$"):
        cached.qualify_cached_review(None, None, None, target={"reviewed": True})  # type: ignore[arg-type]


def test_filepin_bool_size_rejected(tmp_path: Path) -> None:
    file = pin(tmp_path / "file.json", b"{}")
    with pytest.raises(GradebookError, match="FILE_SIZE_REQUIRED"):
        cached._read(replace(file, byte_count=True), private=True)


def test_native_644_source_files_are_read_without_chmod(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
) -> None:
    prepared, native, code = fixture_files(tmp_path, canonical_code)
    native.reading.path.chmod(0o644)
    assert (
        cached.qualify_cached_review(prepared, native, code)["source_qualified"] is True
    )
    assert native.reading.path.stat().st_mode & 0o777 == 0o644


def test_independently_pinned_auxiliary_metadata_is_preserved(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
) -> None:
    prepared, native, code = fixture_files(tmp_path, canonical_code, auxiliary=True)
    result = cached.qualify_cached_review(prepared, native, code)
    assert (
        result["private_preview"]["existing_feedback_reference"]["kind"]
        == "FICTIONAL_REFERENCE"
    )
    with pytest.raises(GradebookError, match="PREPARATION_CHANGED"):
        cached.qualify_cached_review(
            prepared, replace(native, feedback_reference=None), code
        )
    with pytest.raises(GradebookError, match="PREPARATION_CHANGED"):
        cached.qualify_cached_review(
            prepared, replace(native, short_corrections=None), code
        )


def test_preparer_code_must_be_pinned(
    tmp_path: Path,
    canonical_code: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, native, code = fixture_files(tmp_path, canonical_code)

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("No runtime before preparer qualification")

    monkeypatch.setattr(cached.subprocess, "run", forbidden)
    with pytest.raises(GradebookError, match="PREPARER_PIN_REQUIRED"):
        cached.qualify_cached_review(prepared, native, replace(code, preparer=None))


def test_symlink_pin_is_held(tmp_path: Path) -> None:
    original = pin(tmp_path / "original.json", b"{}")
    alias = tmp_path / "alias.json"
    alias.symlink_to(original.path)
    with pytest.raises(GradebookError, match="CHANGED_OR_UNSAFE"):
        cached._read(replace(original, path=alias), private=True)
