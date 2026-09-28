"""Explicit, local, copy-on-write PRIVATE pseudonymous archival exports.

These values-only copies are never operational workbook/baseline inputs.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

PIN = re.compile(r"[0-9]{4}\Z")
EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
)
NAME_HEADERS = {
    "Student Name",
    "Student",
    "Name",
    "student_name",
    "Student name",
    "Canvas Name",
    "IC Name",
    "Roster Name",
}
EMAIL_HEADERS = {"Email", "Student Email", "Email Address", "student_email", "email"}
PIN_HEADERS = {"Student Number", "Student PIN", "PIN"}
RESERVED = {"Points possible", "Assignment IDs"}


class ExportHeld(ValueError):
    """Privacy-safe error code only; never include source values or paths."""


def require(ok: object, code: str) -> None:
    if not ok:
        raise ExportHeld(code)


def fingerprint(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def open_xlsx(path: Path) -> Workbook:
    with ZipFile(path) as archive:
        entries = archive.infolist()
        require(
            len(entries) <= 1000 and sum(x.file_size for x in entries) <= 64_000_000,
            "WORKBOOK_TOO_LARGE",
        )
        require(
            all(x.filename.endswith((".xml", ".rels", ".vml")) for x in entries),
            "UNSUPPORTED_EMBEDDED_CONTENT",
        )
        require(
            not any(
                any(
                    part in x.filename
                    for part in (
                        "charts/",
                        "externalLinks/",
                        "pivot",
                        "embeddings/",
                        "vbaProject",
                        "activeX/",
                        "ctrlProps/",
                        "customXml/",
                    )
                )
                for x in entries
            ),
            "UNSUPPORTED_WORKBOOK_FEATURE",
        )
        for info in entries:
            if info.filename.endswith(".vml"):
                root = ET.fromstring(archive.read(info))
                shapes = root.findall(".//{urn:schemas-microsoft-com:vml}shape")
                require(bool(shapes), "UNSUPPORTED_DRAWING")
                for shape in shapes:
                    data = shape.find(
                        "{urn:schemas-microsoft-com:office:excel}ClientData"
                    )
                    require(
                        data is not None and data.get("ObjectType") == "Note",
                        "UNSUPPORTED_DRAWING",
                    )
            elif "drawings/" in info.filename:
                require(
                    len(ET.fromstring(archive.read(info))) == 0, "UNSUPPORTED_DRAWING"
                )
    book = load_workbook(path, data_only=False, keep_links=False)
    require(sum(len(s._cells) for s in book) <= 200_000, "WORKBOOK_TOO_LARGE")
    return book


def roster_mapping(
    path: Path, sheet_name: str | None = None
) -> tuple[dict[str, set[str]], set[str]]:
    book = open_xlsx(path)
    names = (
        [sheet_name]
        if sheet_name
        else [n for n in ("Student Info", "Student Numbers") if n in book.sheetnames]
    )
    require(
        len(names) == 1 and names[0] in book.sheetnames, "EXACT_ROSTER_SHEET_REQUIRED"
    )
    sheet = book[names[0]]
    rows = []
    for row_number in range(1, min(sheet.max_row, 10) + 1):
        values = [
            sheet.cell(row_number, c).value for c in range(1, sheet.max_column + 1)
        ]
        hits = {
            key: [i for i, v in enumerate(values) if v in labels]
            for key, labels in (
                ("name", NAME_HEADERS),
                ("email", EMAIL_HEADERS),
                ("pin", PIN_HEADERS),
            )
        }
        if len(hits["name"]) >= 1 and len(hits["email"]) == 1 and len(hits["pin"]) == 1:
            rows.append((row_number, hits))
    require(len(rows) == 1, "ROSTER_HEADERS_NOT_UNIQUE")
    header, cols = rows[0]
    aliases: dict[str, set[str]] = defaultdict(set)
    pin_emails: dict[str, set[str]] = defaultdict(set)
    count = 0
    for row in sheet.iter_rows(min_row=header + 1):
        name_values = [row[c].value for c in cols["name"]]
        email, pin = (row[cols[k][0]].value for k in ("email", "pin"))
        if all(v in (None, "") for v in [*name_values, email, pin]):
            continue
        require(
            isinstance(pin, str) and PIN.fullmatch(pin), "FOUR_DIGIT_TEXT_PIN_REQUIRED"
        )
        roster_names = [n for n in name_values if n not in (None, "")]
        require(
            roster_names
            and all(isinstance(n, str) and n.strip() == n and n for n in roster_names),
            "ROSTER_NAME_INVALID",
        )
        require(
            isinstance(email, str) and EMAIL.fullmatch(email), "ROSTER_EMAIL_INVALID"
        )
        require(
            all(row[c].data_type != "f" for indices in cols.values() for c in indices),
            "ROSTER_FORMULA_NOT_ALLOWED",
        )
        assert isinstance(pin, str) and isinstance(email, str)
        for name in roster_names:
            assert isinstance(name, str)
            aliases[name].add(pin)
        aliases[email].add(pin)
        pin_emails[pin].add(email)
        count += 1
    require(
        count > 0 and all(len(v) == 1 for v in pin_emails.values()),
        "ROSTER_PIN_CONFLICT",
    )
    require(
        all(len(v) == 1 for k, v in aliases.items() if EMAIL.fullmatch(k)),
        "ROSTER_EMAIL_CONFLICT",
    )
    return dict(aliases), set(pin_emails)


def text_sanitizer(aliases: dict[str, set[str]]) -> Callable[[Any], Any]:
    # Exact complete identity strings only; no normalization, guesses or new PINs.
    expression = re.compile(
        r"(?<!\w)(?:"
        + "|".join(re.escape(k) for k in sorted(aliases, key=len, reverse=True))
        + r")(?!\w)"
    )

    residual_expression = re.compile(expression.pattern, re.IGNORECASE)

    def sanitize(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        decoded = value
        for _ in range(4):
            next_decoded = html.unescape(unquote(decoded))
            if next_decoded == decoded:
                break
            require(
                not EMAIL.search(next_decoded)
                and not residual_expression.search(next_decoded),
                "ENCODED_IDENTITY_NOT_SUPPORTED",
            )
            decoded = next_decoded
        require(
            html.unescape(unquote(decoded)) == decoded,
            "ENCODING_DEPTH_NOT_SUPPORTED",
        )

        def replace(match: re.Match[str]) -> str:
            choices = aliases[match.group()]
            require(len(choices) == 1, "AMBIGUOUS_IDENTITY_REFERENCE")
            return next(iter(choices))

        try:
            nested = json.loads(value)
        except (ValueError, TypeError):
            nested = None
        if isinstance(nested, (dict, list)):

            def walk(item: Any) -> Any:
                if isinstance(item, dict):
                    keys = [sanitize(k) for k in item]
                    require(len(set(keys)) == len(keys), "SANITIZED_JSON_KEY_CONFLICT")
                    return {
                        key: walk(v) for key, v in zip(keys, item.values(), strict=True)
                    }
                if isinstance(item, list):
                    return [walk(v) for v in item]
                return sanitize(item)

            value = json.dumps(walk(nested), ensure_ascii=False, separators=(",", ":"))
        result = expression.sub(replace, value)
        require(not EMAIL.search(result), "UNMAPPED_EMAIL_REMAINS")
        require(not residual_expression.search(result), "IDENTITY_REMAINS")
        return result

    return sanitize


def replace_columns(
    rows: list[list[Any]], aliases: dict[str, set[str]], pins: set[str]
) -> int:
    """Rows are mutable lists. Discover explicit labels in the first ten rows."""
    headers = []
    for number, row in enumerate(rows[:10]):
        columns = [
            i
            for i, value in enumerate(row)
            if isinstance(value, str) and value in NAME_HEADERS | EMAIL_HEADERS
        ]
        if columns:
            headers.append((number, columns))
    require(len(headers) <= 1, "IDENTITY_HEADERS_NOT_UNIQUE")
    if not headers:
        return 0
    header, columns = headers[0]
    replaced = 0
    for number, row in enumerate(rows[header + 1 :], header + 1):
        values = [row[c] if c < len(row) else None for c in columns]
        if all(v in (None, "") for v in values):
            continue
        # Canonical gradebook has three header rows: Student / Points / IDs.
        if number in (header + 1, header + 2) and all(
            v in (None, "") or v in RESERVED for v in values
        ):
            continue
        candidates = []
        for value in values:
            if value in (None, ""):
                continue
            require(isinstance(value, str), "IDENTITY_NOT_TEXT")
            assert isinstance(value, str)
            choices = {value} if value in pins else aliases.get(value, set())
            # Canonical GET/Edit labels are exact name + newline + sections.
            if not choices and header == 2 and columns == [1] and "\n" in value:
                choices = aliases.get(value.split("\n", 1)[0], set())
            require(bool(choices), "UNMAPPED_IDENTITY")
            candidates.append(choices)
        matching = set.intersection(*candidates)
        require(len(matching) == 1, "IDENTITY_CONFLICT_OR_AMBIGUITY")
        pin = next(iter(matching))
        for c in columns:
            while len(row) <= c:
                row.append(None)
            row[c] = pin
        replaced += 1
    for c in columns:
        rows[header][c] = (
            "Student PIN" if rows[header][c] in NAME_HEADERS else "Student PIN (email)"
        )
    return replaced


def sanitize_export(
    source: Path, central_roster: Path, output: Path, roster_sheet: str | None = None
) -> dict[str, Any]:
    source, central_roster, output = map(Path, (source, central_roster, output))
    require(
        all(p.is_absolute() for p in (source, central_roster, output)),
        "ABSOLUTE_PATH_REQUIRED",
    )
    require(
        source.resolve() != output.resolve()
        and central_roster.resolve() != output.resolve(),
        "ORIGINAL_MUST_BE_PRESERVED",
    )
    require(not output.exists(), "OUTPUT_ALREADY_EXISTS")
    require(output.parent.is_dir(), "OUTPUT_DIRECTORY_REQUIRED")
    require(
        all(not p.is_symlink() for p in (output.parent, *output.parent.parents)),
        "OUTPUT_SYMLINK_NOT_ALLOWED",
    )
    require(
        not any((p / ".git").exists() for p in (output.parent, *output.parent.parents)),
        "ARCHIVE_INSIDE_GIT_NOT_ALLOWED",
    )
    require(
        output.parent.stat().st_mode & 0o077 == 0, "PRIVATE_OUTPUT_DIRECTORY_REQUIRED"
    )
    require(
        source.suffix.lower() in (".xlsx", ".csv")
        and output.suffix.lower() == source.suffix.lower(),
        "FORMAT_NOT_SUPPORTED",
    )
    before, roster_before = fingerprint(source), fingerprint(central_roster)
    aliases, pins = roster_mapping(central_roster, roster_sheet)
    sanitize = text_sanitizer(aliases)
    count = 0
    if source.suffix.lower() == ".csv":
        csv_rows: list[list[Any]] = list(
            csv.reader(io.StringIO(source.read_text(encoding="utf-8-sig")))
        )
        require(len(csv_rows) <= 200_000, "EXPORT_TOO_LARGE")
        count += replace_columns(csv_rows, aliases, pins)
        csv_values = [[sanitize(v) for v in row] for row in csv_rows]
        # CSV cannot declare literal string cells; prevent spreadsheet formulas.
        require(
            not any(
                v.startswith(("=", "+", "-", "@", "\t", "\r"))
                for r in csv_values
                for v in r
            ),
            "CSV_FORMULA_NOT_SUPPORTED",
        )
        csv_stream = io.StringIO(newline="")
        csv.writer(csv_stream).writerows(csv_values)
        payload = csv_stream.getvalue().encode("utf-8")
    else:
        book = open_xlsx(source)
        cached = load_workbook(source, data_only=True, keep_links=False)
        clean = Workbook()
        active = clean.active
        assert active is not None
        clean.remove(active)
        for sheet in book:
            require(
                sheet.max_row * sheet.max_column <= 1_000_000,
                "SHEET_SHAPE_NOT_SUPPORTED",
            )
            rows: list[list[Any]] = []
            for source_row in sheet.iter_rows():
                values: list[Any] = []
                for cell in source_row:
                    value = (
                        cached[sheet.title][cell.coordinate].value
                        if cell.data_type == "f"
                        else cell.value
                    )
                    require(
                        cell.data_type != "f" or value is not None,
                        "FORMULA_CACHE_MISSING",
                    )
                    values.append(value)
                rows.append(values)
            count += replace_columns(rows, aliases, pins)
            title = sanitize(sheet.title)
            require(title not in clean.sheetnames, "SANITIZED_SHEET_TITLE_CONFLICT")
            dest = clean.create_sheet(title)
            dest.sheet_state = sheet.sheet_state
            for row_no, row in enumerate(rows, 1):
                for col_no, value in enumerate(row, 1):
                    if value is None:
                        continue
                    value = sanitize(value)
                    cell = dest.cell(row_no, col_no, value)
                    if isinstance(value, str):
                        cell.data_type = "s"
                        if PIN.fullmatch(value):
                            cell.number_format = "@"
        stream = io.BytesIO()
        clean.save(stream)
        payload = stream.getvalue()
        # Rebuilt package drops all source comments, hyperlinks, names, metadata,
        # validation lists, drawings and cached shared strings, including hidden sheets.
        with ZipFile(io.BytesIO(payload)) as archive:
            for info in archive.infolist():
                text = archive.read(info).decode("utf-8")
                # XML namespaces contain no mailbox addresses. Unescape text first.
                require(
                    sanitize(html.unescape(text)) == html.unescape(text),
                    "OUTPUT_IDENTITY_REMAINS",
                )
    require(count > 0, "NO_IDENTITY_COLUMNS_FOUND")
    require(
        fingerprint(source) == before and fingerprint(central_roster) == roster_before,
        "INPUT_CHANGED",
    )
    require(output.parent.is_dir(), "OUTPUT_DIRECTORY_REQUIRED")
    fd, temporary = tempfile.mkstemp(prefix=".pin-export-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)  # Exclusive creation; never overwrite an archive.
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {
        "status": "PRIVATE_PSEUDONYMOUS_ARCHIVE",
        "identity_rows_replaced": count,
        "source_sha256": before,
        "roster_sha256": roster_before,
        "output_sha256": hashlib.sha256(payload).hexdigest(),
        "originals_preserved": True,
        "live_calls": 0,
    }
