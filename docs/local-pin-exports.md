# Private local PIN archives

Every supported local gradebook export ingested for archiving runs through this explicit command. This is automatic within the ingest action; there is no folder watcher, timer, or background access. Existing working files and live Sheets remain unchanged.

Install the local dependency with `python -m pip install -e '.[local-exports]'`. Then create a private archive directory outside Git (permissions `0700`) and run:

```sh
python scripts/pseudonymize_gradebook_export.py ingest \
  --source /absolute/private/export.xlsx \
  --central-roster /absolute/private/central-gradebook.xlsx \
  --output /absolute/private-archive/export-pins.xlsx
```

CSV uses the same command with `.csv` source/output. The authoritative roster must be an XLSX export of the exact central gradebook. The command reads `Student Info` or `Student Numbers`; if both exist, choose the exact one with `--roster-sheet`. It requires existing four-digit **text** Student Number values. It never creates, renumbers, pads, or guesses PINs. Canvas Name, IC Name, Roster Name, Student Name, and Email aliases are matched exactly. Ambiguous names require other matching row evidence; conflicting or unknown identity cells stop the export. Canonical GET/Edit name-plus-section labels are resolved using the exact name component, then the entire label is replaced by its PIN.

For each populated identity row, the entire recognized name and email columns become the same PIN, including previously blank identity cells. Existing PIN text retains leading zeros. Hidden sheets are included. Known identity references elsewhere (including embedded JSON) are replaced exactly; unknown emails and ambiguous references stop the export. Source comments, hyperlinks, metadata, defined names, validation lists and formatting are omitted from the rebuilt values-only XLSX. Nonempty drawings, media, macros, external workbooks, embedded objects, oversized files and formulas without cached values are unsupported and stop the export. CSV formula-like cells also stop the export. No successful output exists after a validation hold.

The output directory must already be private, have no symlink ancestors and be outside every Git checkout. Output creation is exclusive and mode `0600`; neither an original nor an existing archive is overwritten. Source/roster hashes are checked for changes during processing, and the command prints only aggregate counts, hash receipts and bounded error codes.

These are **private pseudonymous archives**, not anonymized/public datasets. Canvas/IC IDs, grades, sections and source evidence can still identify students; only known roster names and emails are covered. Do not share publicly or add to Git. The values-only copy is not an operational GET/Edit workbook, refresh baseline, or publication input. Keep the exact original privately for operational use and authorized recovery. No credential, Canvas, Drive, model, grading or publication calls occur.

Validation uses synthetic fixtures: `python -m pytest tests/test_pseudonymize_export.py -q`. Required CI installs `.[local-exports]` and runs these tests without optional skipping.
