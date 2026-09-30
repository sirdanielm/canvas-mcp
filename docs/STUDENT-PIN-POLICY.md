# Student PIN policy for local documents

Effective September 28, 2026. Use the same permanent four-digit student PIN in
local working copies, exports, and Quinn's library across SDM projects. Replace
student name and email columns with one `student_pin` column. Keep the original
source and the identity crosswalk private and unchanged.

## One authoritative source

The authority is the **Canvas MCP gradebook mirror's `Student Info` tab** in the
FDHS Chemistry Gradebook, as bound by
`canvas-mcp-sdm-authoring/config/sdm-gradebook-workbooks.json`. It is separate from
the course-content mirror, which does not include student identities or grades.
Resolve `Email` to `Student Number` by header, never by an assumed column position.
The historical `Student Numbers` tab is not the current source contract.

All project launchers use the same private operator registry by default:
`~/QuinnOperator/config/student-pin-source.json`. It records the authority,
trusted local snapshot path and SHA-256, capture time, `Student Info` sheet,
`Email` and `Student Number` columns, and private name columns. The registry and
roster must remain outside Quinn's readable folders and outside Git. A refresh
must update this shared registry after source verification; projects must not
maintain independent PIN assignments or substitute an arbitrary roster.

The local source audit on September 28 checked a previously exported workbook
whose recorded export time was September 27 at 9:12 PM EDT. Its `Student Info`
headers matched the contract, and all 173 retained permanent entries contained
unique four-digit text PINs, including 20 with leading zeros. This is evidence
about that local snapshot, not a fresh live-roster claim.

## Export a new local copy

Run from this checkout:

```sh
python3 scripts/export-student-pins.py --help
python3 scripts/export-student-pins.py \
  --source /private/operator/review.xlsx \
  --source-sheet Review \
  --email-column student_email \
  --keep-column review_status \
  --keep-column teacher_score \
  --output ~/QuinnWorkspace/library/graders/review-pin-copy.json
```

Paths above are examples. The output must be a new `.json` file; the tool never
rewrites the input workbook. CSV, TSV, JSON tables, and XLSX are supported inputs.
Repeat `--email-column` for every relevant student-email field and
`--keep-column` for each reviewed nonidentity field to retain. `--drop-column`
can explicitly mark additional identity columns for exclusion. All remaining
unapproved columns are excluded. Run `--help` for the current complete contract.

This launcher calls the single implementation in the sibling
`LocalGrAss-github/scripts/export-student-pins.py`; it does not maintain a second
mapper. An unavailable shared implementation or registry is a stop, not a reason
to invent a mapping. An explicit `--source-registry` selects an operator-reviewed
registry; `--roster`, when supplied, must match that registry's trusted hash.

The tool preserves leading zeros and uses exact normalized email matches. It
rejects invalid or duplicate mappings and holds records with unmatched or
conflicting identity fields. A hold is not a zero score. It never guesses from a
name, creates or renumbers a PIN, or uses `S` or an attempt/run label as part of the
stored PIN. Several original name/email columns become one `student_pin` field;
no raw identity column is retained in the admitted table or console output.

## Scope and agent rules

- Apply this policy before local student tables enter Quinn's curated workspace
  or another project library. Keep refresh and crosswalk access operator-only.
- PIN-based student work is still private. Do not commit student records, scans,
  source rosters, crosswalks, or generated student exports to GitHub.
- The table exporter does not claim to scrub names from narrative text, scanned
  handwriting, image headers, filenames, comments, or embedded objects. Review
  and redact those separately before including them in a library.
- This local-copy policy does not authorize changing live Canvas, the gradebook
  source, existing operational graders, deployment, grading, or publication.
  Existing exact Canvas IDs remain available only where the original connector
  needs them for authorized reconciliation; they are not copied to Quinn.
- Generic MCP anonymization settings may generate unrelated anonymous labels;
  those labels do not satisfy this cross-project permanent-PIN contract.

Keep the central implementation, shared registry, and this policy aligned. Use
synthetic fixtures for tests and report only aggregate admission/hold counts.
