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
