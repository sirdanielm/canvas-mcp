"""Synthetic-only privacy checks; no fixtures from classroom exports."""

import importlib.util
import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment

_spec = importlib.util.spec_from_file_location(
    "pin_export",
    Path(__file__).parents[1] / "src/canvas_mcp/gradebook/pseudonymize_export.py",
)
assert _spec and _spec.loader
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


@pytest.fixture
def files(tmp_path):
    tmp_path.chmod(0o700)
    roster = tmp_path / "roster.xlsx"
    w = Workbook()
    w.active.title = "Student Info"
    w.active.append(["Canvas Name", "IC Name", "Email", "Student Number"])
    w.active.append(
        ["Fictional Alpha", "Alpha, Fictional", "alpha@example.test", "0123"]
    )
    w.active.append(["Fictional Beta", "Beta, Fictional", "beta@example.test", "0456"])
    w.save(roster)
    return tmp_path, roster


def test_entire_columns_hidden_cells_and_metadata_are_sanitized(files):
    root, roster = files
    source, target = root / "source.xlsx", root / "archive.xlsx"
    w = Workbook()
    w.active.append(["Student Name", "Email", "Grade"])
    w.active.append(["Fictional Alpha", "alpha@example.test", 75])
    w.active["C2"].comment = Comment("Fictional Alpha", "alpha@example.test")
    w.active["C2"].hyperlink = "mailto:alpha@example.test"
    hidden = w.create_sheet("_Sync")
    hidden.sheet_state = "hidden"
    hidden.append(
        [json.dumps({"name": "Fictional Alpha", "email": "alpha@example.test"})]
    )
    w.properties.creator = "Fictional Alpha"
    w.save(source)
    before = module.fingerprint(source)
    result = module.sanitize_export(source, roster, target)
    out = load_workbook(target)
    assert out.active["A2"].value == out.active["B2"].value == "0123"
    assert out.active["A2"].number_format == "@"
    assert out.active["C2"].value == 75
    assert out.active["C2"].comment is out.active["C2"].hyperlink is None
    assert "Fictional Alpha" not in out["_Sync"]["A1"].value
    assert out["_Sync"].sheet_state == "hidden"
    assert module.fingerprint(source) == before
    assert result["identity_rows_replaced"] == 1
    assert target.stat().st_mode & 0o077 == 0


def test_canonical_multiline_label_becomes_one_pin(files):
    root, roster = files
    source, target = root / "source.xlsx", root / "archive.xlsx"
    w = Workbook()
    for row in [
        [None, "Title"],
        [None, "Read only"],
        [None, "Student Name"],
        [None, "Points possible"],
        ["Canvas user ID", "Assignment IDs"],
        ["fictional-id", "Fictional Alpha\nFictional Section"],
    ]:
        w.active.append(row)
    w.save(source)
    module.sanitize_export(source, roster, target)
    assert load_workbook(target).active["B6"].value == "0123"


@pytest.mark.parametrize(
    "values,code",
    [
        (["Fictional Alpha", "beta@example.test"], "IDENTITY_CONFLICT_OR_AMBIGUITY"),
        (["Unknown Fictional Person", "alpha@example.test"], "UNMAPPED_IDENTITY"),
    ],
)
def test_conflicting_or_unknown_identity_holds_without_output(files, values, code):
    root, roster = files
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text("Student Name,Email\n" + ",".join(values) + "\n")
    with pytest.raises(module.ExportHeld, match=code):
        module.sanitize_export(source, roster, target)
    assert not target.exists()


def test_ambiguous_name_requires_exact_unique_evidence(files):
    root, roster = files
    w = load_workbook(roster)
    w.active["A3"] = "Fictional Alpha"
    w.save(roster)
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")
    with pytest.raises(module.ExportHeld, match="IDENTITY_CONFLICT_OR_AMBIGUITY"):
        module.sanitize_export(source, roster, target)
    assert not target.exists()


def test_numeric_pin_and_missing_formula_cache_hold(files):
    root, roster = files
    w = load_workbook(roster)
    w.active["D2"] = 123
    w.save(roster)
    with pytest.raises(module.ExportHeld, match="FOUR_DIGIT_TEXT_PIN_REQUIRED"):
        module.roster_mapping(roster)


def test_json_key_collision_and_unknown_email_hold():
    clean = module.text_sanitizer(
        {"Fictional Alpha": {"0123"}, "Alpha, Fictional": {"0123"}}
    )
    with pytest.raises(module.ExportHeld, match="SANITIZED_JSON_KEY_CONFLICT"):
        clean(json.dumps({"Fictional Alpha": 1, "Alpha, Fictional": 2}))
    with pytest.raises(module.ExportHeld, match="UNMAPPED_EMAIL_REMAINS"):
        clean("unmapped@example.test")


def test_original_overwrite_existing_archive_and_git_output_refused(files):
    root, roster = files
    with pytest.raises(module.ExportHeld, match="ORIGINAL_MUST_BE_PRESERVED"):
        module.sanitize_export(roster, roster, roster)
    (root / ".git").mkdir()
    with pytest.raises(module.ExportHeld, match="ARCHIVE_INSIDE_GIT_NOT_ALLOWED"):
        module.sanitize_export(roster, roster, root / "archive.xlsx")


def test_uncached_formula_and_csv_injection_hold(files):
    root, roster = files
    source, target = root / "source.xlsx", root / "archive.xlsx"
    w = Workbook()
    w.active.append(["Student Name", "Grade"])
    w.active.append(["Fictional Alpha", "=1+1"])
    w.save(source)
    with pytest.raises(module.ExportHeld, match="FORMULA_CACHE_MISSING"):
        module.sanitize_export(source, roster, target)
    csv_source = root / "source.csv"
    csv_source.write_text("Student Name,Grade\nFictional Alpha,=1+1\n")
    with pytest.raises(module.ExportHeld, match="CSV_FORMULA_NOT_SUPPORTED"):
        module.sanitize_export(csv_source, roster, root / "archive.csv")


@pytest.mark.parametrize(
    "encoded",
    [
        "Fictional%20Alpha",
        "alpha%40example.test",
        "alpha%2540example.test",
        "Fictional&#32;Alpha",
        "alpha&#64;example.test",
        '{"email":"alpha%40example.test"}',
    ],
)
def test_encoded_identity_is_rejected(encoded):
    clean = module.text_sanitizer(
        {"Fictional Alpha": {"0123"}, "alpha@example.test": {"0123"}}
    )
    with pytest.raises(module.ExportHeld, match="ENCODED_IDENTITY_NOT_SUPPORTED"):
        clean(encoded)


def test_case_variant_is_held_instead_of_guessed():
    clean = module.text_sanitizer({"Fictional Alpha": {"0123"}})
    with pytest.raises(module.ExportHeld, match="IDENTITY_REMAINS"):
        clean("FICTIONAL ALPHA completed it")


def test_existing_output_private_directory_and_symlink_guards(files):
    root, roster = files
    target = root / "already.xlsx"
    target.write_bytes(b"preserve")
    with pytest.raises(module.ExportHeld, match="OUTPUT_ALREADY_EXISTS"):
        module.sanitize_export(roster, roster, target)
    assert target.read_bytes() == b"preserve"
    public = root / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(module.ExportHeld, match="PRIVATE_OUTPUT_DIRECTORY_REQUIRED"):
        module.sanitize_export(roster, roster, public / "archive.xlsx")
    linked = root / "linked"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(module.ExportHeld, match="OUTPUT_SYMLINK_NOT_ALLOWED"):
        module.sanitize_export(roster, roster, linked / "archive.xlsx")


def test_csv_replaces_both_identity_columns_and_preserves_original(files):
    root, roster = files
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text(
        "Student Name,Email,Grade\nFictional Alpha,alpha@example.test,75\n"
    )
    before = source.read_bytes()
    module.sanitize_export(source, roster, target)
    assert source.read_bytes() == before
    assert "0123,0123,75" in target.read_text()
    assert "Fictional Alpha" not in target.read_text()


def test_media_payload_and_hidden_unknown_email_hold(files):
    from zipfile import ZipFile

    root, roster = files
    source, target = root / "source.xlsx", root / "archive.xlsx"
    w = load_workbook(roster)
    hidden = w.create_sheet("hidden")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "not-in-roster@example.test"
    w.save(source)
    with pytest.raises(module.ExportHeld, match="UNMAPPED_EMAIL_REMAINS"):
        module.sanitize_export(source, roster, target)
    assert not target.exists()
    with ZipFile(source, "a") as archive:
        archive.writestr("xl/media/private.png", b"synthetic image bytes")
    with pytest.raises(module.ExportHeld, match="UNSUPPORTED_EMBEDDED_CONTENT"):
        module.sanitize_export(source, roster, target)
    assert not target.exists()


def test_nested_encoding_beyond_bounded_decoder_is_held():
    from urllib.parse import quote

    encoded = "alpha@example.test"
    for _ in range(5):
        encoded = quote(encoded, safe="")
    clean = module.text_sanitizer({"alpha@example.test": {"0123"}})
    with pytest.raises(module.ExportHeld, match="ENCODING_DEPTH_NOT_SUPPORTED"):
        clean(encoded)


@pytest.fixture
def shared_authority(files, monkeypatch):
    from types import SimpleNamespace

    root, roster = files
    registry_path = root / "registry.json"
    registry = {
        "roster_sheet": "Student Info",
        "roster_sha256": module.fingerprint(roster),
        "roster_path": str(roster),
        "email_column": "Email",
        "pin_column": "Student Number",
        "name_columns": ["Canvas Name", "IC Name"],
    }
    registry_path.write_text(json.dumps(registry))
    calls = []

    def binding(path):
        calls.append("binding")
        bound = json.loads(path.read_text())
        if module.fingerprint(roster) != bound["roster_sha256"]:
            raise ValueError("synthetic mismatch")
        return bound, roster, roster.read_bytes(), module.fingerprint(path)

    def read_table(path, raw, sheet):
        calls.append("read_table")
        w = load_workbook(path)
        records = list(w[sheet].values)
        return list(records[0]), [
            dict(zip(records[0], r, strict=True)) for r in records[1:]
        ]

    def roster_index(headers, rows, bound):
        calls.append("roster_index")
        index, names = {}, {}
        for row in rows:
            pin, email = row["Student Number"], row["Email"]
            if pin in index.values() or email in index:
                raise ValueError("synthetic conflict")
            index[email] = pin
            for column in bound["name_columns"]:
                names.setdefault(row[column].casefold(), set()).add(pin)
        return index, names

    fake = SimpleNamespace(
        binding=binding, read_table=read_table, roster_index=roster_index
    )
    monkeypatch.setattr(module, "load_shared_pin_module", lambda path: fake)
    return root, roster, registry_path, calls


def test_registry_path_reuses_shared_binding_and_index(shared_authority):
    root, roster, registry, calls = shared_authority
    result = module.registry_bound_export(
        roster, root / "archive.xlsx", registry, root / "shared.py"
    )
    assert calls == ["binding", "read_table", "roster_index"]
    assert result["shared_pin_authority"] is True
    assert result["registry_sha256"] == module.fingerprint(registry)
    assert load_workbook(root / "archive.xlsx").active["A2"].value == "0123"


def test_registry_roster_hash_mismatch_fails_closed(shared_authority):
    root, roster, registry, _ = shared_authority
    roster.write_bytes(roster.read_bytes() + b"changed")
    with pytest.raises(module.ExportHeld, match="SHARED_PIN_AUTHORITY_REJECTED"):
        module.registry_bound_export(
            roster, root / "archive.xlsx", registry, root / "shared.py"
        )
    assert not (root / "archive.xlsx").exists()


def test_shared_mapping_conflict_is_not_replaced_by_local_mapping(shared_authority):
    root, roster, registry, _ = shared_authority
    w = load_workbook(roster)
    w.active["D3"] = "0123"
    w.save(roster)
    value = json.loads(registry.read_text())
    value["roster_sha256"] = module.fingerprint(roster)
    registry.write_text(json.dumps(value))
    with pytest.raises(module.ExportHeld, match="SHARED_PIN_AUTHORITY_REJECTED"):
        module.registry_bound_export(
            roster, root / "archive.xlsx", registry, root / "shared.py"
        )
    assert not (root / "archive.xlsx").exists()


def test_missing_shared_implementation_fails_closed(files):
    root, roster = files
    with pytest.raises(module.ExportHeld, match="SHARED_PIN_TOOL_UNAVAILABLE"):
        module.registry_bound_export(
            roster, root / "archive.xlsx", root / "registry.json", root / "missing.py"
        )
    assert not (root / "archive.xlsx").exists()


def test_shared_default_resolves_canonical_worktree_sibling(tmp_path):
    canonical = tmp_path / "repos" / "canvas"
    gitdir = canonical / ".git" / "worktrees" / "isolated"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..")
    worktree = tmp_path / "isolated"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: " + str(gitdir))
    assert (
        module.default_shared_pin_tool(worktree)
        == canonical.parent / "LocalGrAss-github/scripts/export-student-pins.py"
    )


def test_registry_change_during_rendering_prevents_archive(
    shared_authority, monkeypatch
):
    root, roster, registry, _ = shared_authority
    original_save = Workbook.save

    def changed_registry_save(book, destination):
        original_save(book, destination)
        registry.write_text(registry.read_text() + " ")

    monkeypatch.setattr(Workbook, "save", changed_registry_save)
    with pytest.raises(module.ExportHeld, match="SHARED_PIN_REGISTRY_CHANGED"):
        module.registry_bound_export(
            roster, root / "archive.xlsx", registry, root / "shared.py"
        )
    assert not (root / "archive.xlsx").exists()
    assert not list(root.glob(".pin-export-*"))


@pytest.mark.parametrize(
    "address",
    [
        "prefix+alpha@example.test",
        "alpha@example.test.evil",
        "other.alpha@example.test",
        "éalpha@example.test",
        "alpha@example.testé",
        '"alpha"@example.test',
        "alpha@localhost",
        "alpha@example.test\u0301",
    ],
)
def test_complete_unknown_email_cannot_be_hidden_by_partial_replacement(address):
    clean = module.text_sanitizer({"alpha@example.test": {"0123"}, "alpha": {"0123"}})
    with pytest.raises(module.ExportHeld, match="UNMAPPED_EMAIL_REMAINS"):
        clean(address)
    with pytest.raises(module.ExportHeld, match="UNMAPPED_EMAIL_REMAINS"):
        clean(json.dumps({"note": address}))
    assert clean("Contact alpha@example.test") == "Contact 0123"


def test_shared_normalized_name_ambiguity_is_preserved(shared_authority):
    root, roster, registry, _ = shared_authority
    book = load_workbook(roster)
    book.active["A3"] = "FICTIONAL ALPHA"
    book.save(roster)
    bound = json.loads(registry.read_text())
    bound["roster_sha256"] = module.fingerprint(roster)
    registry.write_text(json.dumps(bound))
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")
    with pytest.raises(module.ExportHeld, match="IDENTITY_CONFLICT_OR_AMBIGUITY"):
        module.registry_bound_export(source, target, registry, root / "shared.py")
    assert not target.exists()
    source.write_text(
        "Student Name,Email,Note\nFictional Alpha,alpha@example.test,Fictional Alpha\n"
    )
    with pytest.raises(module.ExportHeld, match="AMBIGUOUS_IDENTITY_REFERENCE"):
        module.registry_bound_export(source, target, registry, root / "shared.py")
    assert not target.exists()
    source.write_text("Student Name,Email\nFictional Alpha,alpha@example.test\n")
    module.registry_bound_export(source, target, registry, root / "shared.py")
    assert "0123,0123" in target.read_text()


def test_formula_and_value_readers_use_captured_source_bytes(files, monkeypatch):
    import io

    root, roster = files
    source, target = root / "source.xlsx", root / "archive.xlsx"
    source.write_bytes(roster.read_bytes())
    original = source.read_bytes()
    seen = []
    original_load = module.load_workbook

    def snapshot_load(value, **kwargs):
        assert isinstance(value, io.BytesIO)
        seen.append((kwargs.get("data_only"), value.getvalue()))
        # A temporary path change must never switch the bytes parsed by a later
        # cache/formula pass; restore before the final on-disk change check.
        if kwargs.get("data_only") is True:
            source.write_bytes(original)
        else:
            source.write_bytes(b"different bytes while rendering")
        return original_load(value, **kwargs)

    monkeypatch.setattr(module, "load_workbook", snapshot_load)
    result = module.sanitize_export(source, roster, target)
    assert len(seen) == 3
    assert all(raw == original for _, raw in seen)
    assert result["source_sha256"] == module.fingerprint(source)
    assert load_workbook(target).active["A2"].value == "0123"


@pytest.mark.parametrize("changed_input", ["source", "roster"])
def test_input_changed_while_staging_is_held(files, monkeypatch, changed_input):
    root, roster = files
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")
    original_fsync = module.os.fsync

    def change_after_flush(fd):
        original_fsync(fd)
        changed = source if changed_input == "source" else roster
        changed.write_bytes(changed.read_bytes() + b"changed")

    monkeypatch.setattr(module.os, "fsync", change_after_flush)
    with pytest.raises(module.ExportHeld, match="INPUT_CHANGED"):
        module.sanitize_export(source, roster, target)
    assert not target.exists()
    assert not list(root.glob(".pin-export-*"))


@pytest.mark.parametrize("change", ["mode", "git", "directory", "symlink"])
def test_private_output_binding_is_rechecked_before_publish(files, monkeypatch, change):
    root, roster = files
    source = root / "source.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")
    directory = root / "archive"
    directory.mkdir(mode=0o700)
    target = directory / "copy.csv"
    moved = root / "moved"
    other = root / "other"
    other.mkdir(mode=0o700)
    original_fsync = module.os.fsync

    def change_after_flush(fd):
        original_fsync(fd)
        if change == "mode":
            directory.chmod(0o755)
        elif change == "git":
            (directory / ".git").mkdir()
        else:
            directory.rename(moved)
            if change == "directory":
                directory.mkdir(mode=0o700)
            else:
                directory.symlink_to(other, target_is_directory=True)

    monkeypatch.setattr(module.os, "fsync", change_after_flush)
    with pytest.raises(module.ExportHeld):
        module.sanitize_export(source, roster, target)
    assert not target.exists()
    assert not (moved / "copy.csv").exists()
    assert not (other / "copy.csv").exists()
    assert not list(root.rglob(".pin-export-*"))


@pytest.mark.parametrize(
    "failure", ["unlink", "directory_fsync", "link_after_creation"]
)
def test_after_publication_failure_is_explicitly_uncertain(files, monkeypatch, failure):
    root, roster = files
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")
    original_unlink, original_fsync, original_link = (
        module.os.unlink,
        module.os.fsync,
        module.os.link,
    )

    def unlink(path, **kwargs):
        if failure == "unlink" and str(path).startswith(".pin-export-"):
            raise OSError("synthetic cleanup failure with private text")
        return original_unlink(path, **kwargs)

    def fsync(fd):
        if failure == "directory_fsync" and target.exists():
            raise OSError("synthetic directory sync failure")
        return original_fsync(fd)

    def link(*args, **kwargs):
        original_link(*args, **kwargs)
        if failure == "link_after_creation":
            raise OSError("synthetic ambiguous link completion")

    monkeypatch.setattr(module.os, "unlink", unlink)
    monkeypatch.setattr(module.os, "fsync", fsync)
    monkeypatch.setattr(module.os, "link", link)
    with pytest.raises(
        module.ExportPublicationUncertain, match="ARCHIVE_PUBLICATION_UNCERTAIN"
    ):
        module.sanitize_export(source, roster, target)
    assert "0123,75" in target.read_text()
    assert target.stat().st_mode & 0o077 == 0


def test_duplicate_zip_member_holds_without_output(files):
    from zipfile import ZipFile

    root, roster = files
    source, target = root / "source.xlsx", root / "archive.xlsx"
    source.write_bytes(roster.read_bytes())
    with ZipFile(source, "a") as archive:
        name = "xl/worksheets/sheet1.xml"
        raw = archive.read(name)
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(name, raw)
    with pytest.raises(module.ExportHeld, match="DUPLICATE_WORKBOOK_MEMBER"):
        module.sanitize_export(source, roster, target)
    assert not target.exists()


def test_cli_missing_optional_dependency_returns_bounded_hold(tmp_path):
    import subprocess
    import sys

    script = Path(__file__).parents[1] / "scripts/pseudonymize_gradebook_export.py"
    result = subprocess.run(
        [sys.executable, "-S", str(script), "ingest"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert json.loads(result.stderr) == {
        "status": "HELD",
        "reason": "LOCAL_EXPORT_DEPENDENCY_MISSING",
    }
    assert result.stdout == ""
    assert "Traceback" not in result.stderr


def test_cli_distinguishes_uncertain_publication_from_validation_hold(
    monkeypatch, capsys
):
    import sys

    script = Path(__file__).parents[1] / "scripts/pseudonymize_gradebook_export.py"
    spec = importlib.util.spec_from_file_location("pin_cli_test", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    def uncertain(*args):
        raise cli.module.ExportPublicationUncertain("private details must never appear")

    monkeypatch.setattr(cli.module, "registry_bound_export", uncertain)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "ingest",
            "--source",
            "/synthetic/source.csv",
            "--output",
            "/synthetic/output.csv",
            "--shared-pin-tool",
            "/synthetic/tool.py",
        ],
    )
    assert cli.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "ARCHIVE_PUBLICATION_UNCERTAIN",
        "reason": "CHECK_PRIVATE_OUTPUT_BEFORE_RETRY",
    }


def test_temporary_replacement_is_not_published_or_deleted(files, monkeypatch):
    root, roster = files
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")
    original_fsync = module.os.fsync
    replaced = []

    def replace_after_flush(fd):
        original_fsync(fd)
        temporary = next(root.glob(".pin-export-*"))
        temporary.rename(root / "retained-owned-temporary")
        temporary.write_bytes(b"foreign content must be preserved")
        replaced.append(temporary)

    monkeypatch.setattr(module.os, "fsync", replace_after_flush)
    with pytest.raises(module.ExportHeld, match="TEMPORARY_OUTPUT_CHANGED"):
        module.sanitize_export(source, roster, target)
    assert not target.exists()
    assert replaced[0].read_bytes() == b"foreign content must be preserved"


def test_concurrent_output_creation_is_preserved(files, monkeypatch):
    root, roster = files
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")
    original_fsync = module.os.fsync

    def create_after_flush(fd):
        original_fsync(fd)
        target.write_bytes(b"existing archive from another invocation")

    monkeypatch.setattr(module.os, "fsync", create_after_flush)
    with pytest.raises(module.ExportHeld, match="OUTPUT_ALREADY_EXISTS"):
        module.sanitize_export(source, roster, target)
    assert target.read_bytes() == b"existing archive from another invocation"
    assert not list(root.glob(".pin-export-*"))


def test_malformed_csv_is_held_without_collapsing_rows(files):
    root, roster = files
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text(
        'Student Name,Grade,Note\nFictional Alpha,75,"unterminated\nFictional Beta,80,second row\n'
    )
    with pytest.raises(module.ExportHeld, match="CSV_INVALID"):
        module.sanitize_export(source, roster, target)
    assert not target.exists()
    assert not list(root.glob(".pin-export-*"))


def test_valid_multiline_csv_preserves_rows_and_values(files):
    import csv

    root, roster = files
    source, target = root / "source.csv", root / "archive.csv"
    source.write_text(
        'Student Name,Grade,Note\nFictional Alpha,75,"first\nsecond"\nFictional Beta,80,third\n'
    )
    result = module.sanitize_export(source, roster, target)
    with target.open(newline="") as handle:
        rows = list(csv.reader(handle, strict=True))
    assert rows[1:] == [["0123", "75", "first\nsecond"], ["0456", "80", "third"]]
    assert result["identity_rows_replaced"] == 2


@pytest.mark.parametrize(
    "encoded", ['"Fictional\\u0020Alpha"', '"alpha\\u0040example.test"']
)
def test_json_scalar_string_is_sanitized_without_losing_string_type(encoded):
    clean = module.text_sanitizer(
        {"Fictional Alpha": {"0123"}, "alpha@example.test": {"0123"}}
    )
    assert clean(encoded) == '"0123"'
    assert clean(json.dumps(encoded)) == json.dumps('"0123"')


@pytest.mark.parametrize(
    "encoded",
    [
        '"unknown\\u0040example.test"',
        '{"grade":75,"grade":80}',
        '{"outer":{"grade":75,"grade":80}}',
    ],
)
def test_json_scalar_unknown_email_and_duplicate_keys_hold(encoded):
    clean = module.text_sanitizer(
        {"Fictional Alpha": {"0123"}, "alpha@example.test": {"0123"}}
    )
    with pytest.raises(
        module.ExportHeld, match="UNMAPPED_EMAIL_REMAINS|DUPLICATE_JSON_KEY"
    ):
        clean(encoded)


def test_directory_moves_during_link_are_reported_as_publication_uncertain(
    files, monkeypatch
):
    root, roster = files
    source = root / "source.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")
    directory = root / "archive"
    directory.mkdir(mode=0o700)
    target = directory / "copy.csv"
    moved = root / "moved"
    original_link = module.os.link

    def move_during_link(*args, **kwargs):
        directory.rename(moved)
        original_link(*args, **kwargs)

    monkeypatch.setattr(module.os, "link", move_during_link)
    with pytest.raises(
        module.ExportPublicationUncertain, match="ARCHIVE_PUBLICATION_UNCERTAIN"
    ):
        module.sanitize_export(source, roster, target)
    assert not target.exists()
    assert "0123,75" in (moved / "copy.csv").read_text()
    assert not list(moved.glob(".pin-export-*"))


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_registry_preflight_uses_complete_renderer_without_publisher(
    shared_authority, monkeypatch, suffix
):
    root, roster, registry, calls = shared_authority
    source = root / ("source" + suffix)
    if suffix == ".csv":
        source.write_text(
            "Student Name,Email,Grade\nFictional Alpha,alpha@example.test,75\n"
        )
    else:
        source.write_bytes(roster.read_bytes())
    before = {p.name: module.fingerprint(p) for p in root.iterdir() if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("preflight reached the output publisher")

    monkeypatch.setattr(module, "private_directory_identity", forbidden)
    monkeypatch.setattr(module.os, "link", forbidden)
    result = module.registry_bound_export(
        source,
        None,
        registry,
        root / "shared.py",
        validate_only=True,
        expected_source_hash=module.fingerprint(source),
    )
    assert result["status"] == "PRIVATE_ARCHIVE_PREFLIGHT_READY"
    assert result["archive_created"] is result["destination_validated"] is False
    assert result["shared_pin_authority"] is True
    assert result["source_sha256"] == module.fingerprint(source)
    assert "output_sha256" not in result
    assert calls == ["binding", "read_table", "roster_index"]
    assert {
        p.name: module.fingerprint(p) for p in root.iterdir() if p.is_file()
    } == before


@pytest.mark.parametrize("validate_only", [False, True])
def test_expected_source_hash_holds_before_rendering(files, monkeypatch, validate_only):
    root, roster = files
    source = root / "source.csv"
    source.write_text("Student Name,Grade\nFictional Alpha,75\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("changed QC bytes must not be rendered")

    monkeypatch.setattr(module, "roster_mapping", forbidden)
    with pytest.raises(module.ExportHeld, match="SOURCE_HASH_MISMATCH"):
        module.sanitize_export(
            source,
            roster,
            None if validate_only else root / "archive.csv",
            validate_only=validate_only,
            expected_source_hash="0" * 64,
        )
    assert not (root / "archive.csv").exists()


def test_preflight_preserves_unknown_identity_hold(shared_authority):
    root, roster, registry, _ = shared_authority
    source = root / "source.csv"
    source.write_text("Student Name,Email\nFictional Alpha,unknown@example.test\n")
    before = set(root.iterdir())
    with pytest.raises(module.ExportHeld, match="UNMAPPED_IDENTITY"):
        module.registry_bound_export(
            source,
            None,
            registry,
            root / "shared.py",
            validate_only=True,
        )
    assert set(root.iterdir()) == before


def test_preflight_rechecks_authority_after_rendering(shared_authority, monkeypatch):
    root, roster, registry, _ = shared_authority
    original = Workbook.save

    def change_authority(book, destination):
        original(book, destination)
        registry.write_text(registry.read_text() + " ")

    monkeypatch.setattr(Workbook, "save", change_authority)
    with pytest.raises(module.ExportHeld, match="SHARED_PIN_REGISTRY_CHANGED"):
        module.registry_bound_export(
            roster,
            None,
            registry,
            root / "shared.py",
            validate_only=True,
        )
    assert not list(root.glob(".pin-export-*"))


def test_cli_preflight_dispatches_without_output_path(monkeypatch, capsys):
    import sys

    script = Path(__file__).parents[1] / "scripts/pseudonymize_gradebook_export.py"
    spec = importlib.util.spec_from_file_location("pin_preflight_cli_test", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    calls = []

    def preflight(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "PRIVATE_ARCHIVE_PREFLIGHT_READY", "archive_created": False}

    monkeypatch.setattr(cli.module, "registry_bound_export", preflight)
    argv = [
        str(script),
        "preflight",
        "--source",
        "/synthetic/source.csv",
        "--shared-pin-tool",
        "/synthetic/tool.py",
        "--expected-source-sha256",
        "a" * 64,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    assert calls[0][0][1] is None
    assert calls[0][1] == {"validate_only": True, "expected_source_hash": "a" * 64}
    assert json.loads(capsys.readouterr().out)["archive_created"] is False
    monkeypatch.setattr(sys, "argv", argv + ["--output", "/synthetic/archive.csv"])
    assert cli.main() == 1
    assert (
        json.loads(capsys.readouterr().err)["reason"] == "PREFLIGHT_OUTPUT_NOT_ALLOWED"
    )
    assert len(calls) == 1
