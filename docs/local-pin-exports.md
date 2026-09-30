# Private local PIN archives

Prepare private archival copies only through an explicit authorized ingest action. Reading a QC status does not start an export. There is no folder watcher, timer, or background access; existing working files and live Sheets remain unchanged.

Use Python 3.11 or newer (the CLI refuses older interpreters before reading exports). Install the local dependency with `python -m pip install -e '.[local-exports]'`. Then create a private archive directory outside Git (permissions `0700`) and run:

```sh
python scripts/pseudonymize_gradebook_export.py ingest \
  --source /absolute/private/export.xlsx \
  --output /absolute/private-archive/export-pins.xlsx
```

CSV uses the same command with `.csv` source/output. CSV stores PIN digits as text bytes but cannot declare spreadsheet cell types; when opening one in a spreadsheet application, import the PIN columns as text to retain leading zeros. XLSX outputs explicitly store PIN cells as text. The CLI always uses the shared source registry at `~/QuinnOperator/config/student-pin-source.json`, or an explicit operator-reviewed `--source-registry`. Its roster path and exact SHA-256 must validate through the shared LocalGrAss `binding()` and `roster_index()` implementation. Arbitrary `--central-roster` substitution is not accepted; the current contract requires `Student Info`.

Use `preflight` to assess compatibility through the same complete renderer and
shared identity authority without creating an archive or specifying an output:

```sh
python scripts/pseudonymize_gradebook_export.py preflight \
  --source /absolute/private/export.xlsx \
  --expected-source-sha256 EXACT_SHA256_FROM_THE_QC_REPORT
```

The optional expected hash binds the exact source checked by QC; a mismatch
holds before rendering. It is also supported by `ingest`. Preflight returns
`PRIVATE_ARCHIVE_PREFLIGHT_READY` only after rendering in memory and rechecking
the source, roster and registry. It returns the same bounded identity/content
holds as ingest. It creates no archive or publication temporary file, accepts no
`--output`, and does not validate any destination. Spreadsheet serialization may
use the library's private temporary scratch files, which it removes normally.
A passing preflight is a point-in-time compatibility result: an eventual ingest
must repeat every check and validate its private destination. It does not clear
QC findings, approve publication, or automatically activate the desktop hook.

The shared implementation is discovered in the canonical sibling `LocalGrAss-github`, including when this renderer runs in a Git worktree. `--shared-pin-tool /absolute/LocalGrAss-github/scripts/export-student-pins.py` can select an explicit installation. Missing implementation, invalid registry, changed roster hash or rejected mapping stops before an archive is created. This renderer does not initialize a Canvas server or contact services.

Every PIN comes from that shared validated index. Original roster spellings are retained only for exact substitution in the private whole-workbook renderer. Existing four-digit text PINs retain leading zeros; none are created, padded or renumbered. Conflicting or unknown identity cells stop the export. Name ambiguity remains governed by the shared canonical index even when two source spellings differ by case. Canonical GET/Edit name-plus-section labels use the exact name component and replace the entire label. Whole-workbook archives remain operator-private and are not Quinn library admissions; the shared table exporter remains the path for explicitly selected, allowlisted `student_pin` JSON tables.

For each populated identity row, the entire recognized name and email columns become the same PIN, including previously blank identity cells. Existing PIN text retains leading zeros. Hidden sheets are included. Known identity references elsewhere (including embedded JSON) are replaced exactly; unknown emails and ambiguous references stop the export. Source comments, hyperlinks, metadata, defined names, validation lists and formatting are omitted from the rebuilt values-only XLSX. Nonempty drawings, media, macros, external workbooks, embedded objects, oversized files and formulas without cached values are unsupported and stop the export. CSV formula-like cells also stop the export. Validation holds create no new archive; existing files remain unchanged. Unsupported mailbox forms also hold rather than permitting a partial replacement.

The output directory must already be private, have no symlink ancestors and be outside every Git checkout. Output creation is exclusive and mode `0600`; neither an original nor an existing archive is overwritten. The parser and receipt use one captured source/roster byte snapshot, with hashes checked again before publication. The writer pins the private directory identity and rechecks its permissions, symlink and Git boundaries before exclusive creation and again after publication. The command prints only aggregate counts, hash receipts and bounded error codes.

A failure after publication begins returns `ARCHIVE_PUBLICATION_UNCERTAIN` with exit code 2. An output or private temporary file may remain; inspect and reconcile that exact destination before retrying. Do not delete it automatically or treat the failure as proof that nothing was written. Ordinary validation holds return exit code 1; successful private creation returns 0.

These are **private pseudonymous archives**, not anonymized/public datasets. Canvas/IC IDs, grades, sections and source evidence can still identify students; only known roster names and emails are covered. Do not share publicly or add to Git. The values-only copy is not an operational GET/Edit workbook, refresh baseline, or publication input. Keep the exact original privately for operational use and authorized recovery. No credential, Canvas, Drive, model, grading or publication calls occur.

Formula caches are captured values from the original file, not freshly recalculated results. These archives do not prove that their source matches current Canvas.

Validation uses synthetic fixtures: `python -m pytest tests/test_pseudonymize_export.py -q`. Required CI installs `.[local-exports]` and runs these tests without optional skipping. The default development group also includes the spreadsheet runtime, so `uv run --locked python -m pytest tests/ -q` can collect the complete suite without a separate manual dependency step.

Malformed CSV quoting and duplicate keys in embedded JSON hold the archive rather than silently dropping content. Valid multiline CSV and escaped JSON string identities are covered by regression tests.

The [September 30 validation receipt](validation/private-pin-export-20260930.json) records 2,158 passing Python tests, 21 existing skips, 58 exporter tests, 96 TypeScript tests and 22 menu tests. Its synthetic CLI smoke exercised the actual shared binding/index implementation. These checks do not clear the historical fleet compatibility holds or establish real-data anonymization.
