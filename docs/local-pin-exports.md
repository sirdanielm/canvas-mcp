# Private local PIN archives

Every supported local gradebook export ingested for archiving runs through this explicit command. This is automatic within the ingest action; there is no folder watcher, timer, or background access. Existing working files and live Sheets remain unchanged.

Use Python 3.11 or newer (the CLI refuses older interpreters before reading exports). Install the local dependency with `python -m pip install -e '.[local-exports]'`. Then create a private archive directory outside Git (permissions `0700`) and run:

```sh
python scripts/pseudonymize_gradebook_export.py ingest \
  --source /absolute/private/export.xlsx \
  --output /absolute/private-archive/export-pins.xlsx
```

CSV uses the same command with `.csv` source/output. The CLI always uses the shared source registry at `~/QuinnOperator/config/student-pin-source.json`, or an explicit operator-reviewed `--source-registry`. Its roster path and exact SHA-256 must validate through the shared LocalGrAss `binding()` and `roster_index()` implementation. Arbitrary `--central-roster` substitution is not accepted; the current contract requires `Student Info`.

The shared implementation is discovered in the canonical sibling `LocalGrAss-github`, including when this renderer runs in a Git worktree. `--shared-pin-tool /absolute/LocalGrAss-github/scripts/export-student-pins.py` can select an explicit installation. Missing implementation, invalid registry, changed roster hash or rejected mapping stops before an archive is created. This renderer does not initialize a Canvas server or contact services.

Every PIN comes from that shared validated index. Original roster spellings are retained only for exact substitution in the private whole-workbook renderer. Existing four-digit text PINs retain leading zeros; none are created, padded or renumbered. Conflicting or unknown identity cells stop the export. Canonical GET/Edit name-plus-section labels use the exact name component and replace the entire label. Whole-workbook archives remain operator-private and are not Quinn library admissions; the shared table exporter remains the path for explicitly selected, allowlisted `student_pin` JSON tables.

For each populated identity row, the entire recognized name and email columns become the same PIN, including previously blank identity cells. Existing PIN text retains leading zeros. Hidden sheets are included. Known identity references elsewhere (including embedded JSON) are replaced exactly; unknown emails and ambiguous references stop the export. Source comments, hyperlinks, metadata, defined names, validation lists and formatting are omitted from the rebuilt values-only XLSX. Nonempty drawings, media, macros, external workbooks, embedded objects, oversized files and formulas without cached values are unsupported and stop the export. CSV formula-like cells also stop the export. No successful output exists after a validation hold.

The output directory must already be private, have no symlink ancestors and be outside every Git checkout. Output creation is exclusive and mode `0600`; neither an original nor an existing archive is overwritten. Source/roster hashes are checked for changes during processing, and the command prints only aggregate counts, hash receipts and bounded error codes.

These are **private pseudonymous archives**, not anonymized/public datasets. Canvas/IC IDs, grades, sections and source evidence can still identify students; only known roster names and emails are covered. Do not share publicly or add to Git. The values-only copy is not an operational GET/Edit workbook, refresh baseline, or publication input. Keep the exact original privately for operational use and authorized recovery. No credential, Canvas, Drive, model, grading or publication calls occur.

Validation uses synthetic fixtures: `python -m pytest tests/test_pseudonymize_export.py -q`. Required CI installs `.[local-exports]` and runs these tests without optional skipping.
