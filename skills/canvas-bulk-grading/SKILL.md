---
name: canvas-bulk-grading
description: Bulk grading workflows for Canvas LMS assignments using rubrics. Covers single grading, batch grading, and code execution strategies with safety-first dry runs.
---

# Canvas Bulk Grading

Grade Canvas LMS assignments efficiently using rubric-based workflows. This skill requires the Canvas MCP server to be running and authenticated with an instructor or TA token.

## Prerequisites

- Canvas MCP server running and connected
- Authenticated with an **educator** (instructor/TA) Canvas API token
- Assignment must exist and have submissions to grade
- Rubric must be created and associated with the assignment with `use_for_grading=true`. Use `create_rubric` for creation and `associate_rubric` for an existing rubric; use `update_rubric` (two-call preview + token) for text/point edits; add or remove criteria in the Canvas UI.

## Workflow

### Step 1: Gather Assignment and Rubric Information

Before grading, retrieve the assignment details and its rubric criteria.

```
get_assignment_details(course_identifier, assignment_id)
```

Then get the rubric. Use `get_rubric` if the rubric is already linked to the assignment, or `list_rubrics` to browse all rubrics in the course:

```
get_rubric(course_identifier, assignment_id=assignment_id)
list_rubrics(course_identifier)
get_rubric(course_identifier, rubric_id=rubric_id)
```

Record the **criterion IDs** (often prefixed with underscore, e.g., `_8027`) and **rating IDs** from the rubric response. These are required for rubric-based grading.

Use the assignment-associated rubric, verify `use_rubric_for_grading=true`, and use every real criterion ID, including criteria awarded zero points. A partial assessment may be dispatched before the result is reported unconfirmed; inspect Canvas before retrying. Single-criterion examples below assume that criterion is the complete assignment rubric.

### Step 2: List Submissions

Retrieve all student submissions to determine how many need grading:

```
list_submissions(course_identifier, assignment_id)
```

Record the user ID, submitted time, score and grade returned by `list_submissions`.
It does not expose `workflow_state`; do not classify `pending_review` from this
output. Hold uncertain eligibility until separately verified.

### Step 3: Choose a Grading Strategy

Reuse the assignment and scope already specified. Hold uncertain targets separately and continue independent eligible submissions. Choose among tools that are actually enabled; class size alone never requires general code execution:

```
How many submissions need grading?
|
+-- 1-9 submissions
|   Use grade_with_rubric (one call per submission)
|
+-- Multiple submissions, including large classes
|   Use bulk_grade_submissions (concurrent batch processing)
|   Set max_concurrent: 5, rate_limit_delay: 1.0
|   Run with dry_run: true first (Safety Rule 1)
|
+-- Custom logic that warrants enabled, authorized code execution
    Use execute_typescript with bulkGrade function
    Grading logic runs locally; only selected output returns to the model
    Pass dryRun: true on the first run
```

### Strategy A: Single Grading (1-9 submissions)

Call `grade_with_rubric` once per student:

```
grade_with_rubric(
  course_identifier,
  assignment_id,
  user_id,
  rubric_assessment: {
    "criterion_id": {
      "points": <number>,
      "rating_id": "<string>",    // optional
      "comments": "<string>"      // optional per-criterion feedback
    }
  },
  comment: "Overall feedback"     // optional
)
```

### Strategy B: Bulk Grading (any supported batch size)

**Validate a new substantive payload before sending.** Build the grades dictionary mapping each user ID to its grade data. Use `dry_run: true` for the nonwriting validation; reuse valid unchanged results while retaining fresh target checks:

```
bulk_grade_submissions(
  course_identifier,
  assignment_id,
  grades: {
    "user_id_1": {
      "rubric_assessment": {
        "criterion_id": {"points": 85, "comments": "Good analysis"}
      },
      "comment": "Overall feedback"
    },
    "user_id_2": {
      "grade": 92,
      "comment": "Excellent work"
    }
  },
  dry_run: true,          // VALIDATE FIRST
  max_concurrent: 5,
  rate_limit_delay: 1.0
)
```

Review the dry-run results and apply only grades/feedback covered by the instructor’s actual publication authorization. If the exact payload is already approved, reuse that approval across unchanged bounded batches; do not ask for another generic plan approval. Ask when final academic acceptance or publication authority is missing, or targets/values/feedback materially change. A successful dry run is not approval.

### Strategy C: Enabled Code Execution for Custom Logic

For custom logic, enabled code execution can keep per-item processing out of the conversation context. Prefer `bulk_grade_submissions` for ordinary batches of any supported size, splitting into bounded batches if necessary. If code execution is absent, continue through an available supported bulk path.

`execute_typescript` is off by default and disabled in the supplied hosted deployment
configuration. Enabling it requires separately reviewed operator configuration.
It requires `EXECUTE_TYPESCRIPT_ENABLED=true`; when `ALLOWED_WRITE_TOOLS` is set,
name `execute_typescript` explicitly (`all` does not include it). Treat every run
as fully privileged Canvas access: code can bypass MCP confirmation tokens and
content fencing. Run only within explicit user authorization for the intended scope and effects;
existing authorization remains valid. A missing tool is an operator boundary, not a reason to bypass it.

The helper and captured execution output can include per-student identifiers,
including during dry runs. Keep that output private and report only aggregate
results to the conversation; do not assume local processing anonymizes stdout.

`bulkGrade({dryRun: true, ...})` skips its own grade submission, but still runs
your callback. It does not validate the returned grades against Canvas or a rubric,
and cannot prevent a callback from making its own writes. Keep preview callbacks
free of side effects and review the exact intended changes. Apply only within
existing instructor authorization or obtain it when missing. A `graded` count during dry run means
would-be results, not saved grades. Use `grade` for a direct score or
`rubricAssessment` for rubric scoring; top-level `points` is deprecated and ignored.


```
execute_typescript(code: `
  import { bulkGrade } from './canvas/grading/bulkGrade.js';

  await bulkGrade({
    courseIdentifier: "COURSE_ID",
    assignmentId: "ASSIGNMENT_ID",
    dryRun: true,  // callback preview only; apply only after explicit instructor approval
    gradingFunction: (submission) => {
      // Local processing; any model/API cost depends on the callback.
      const notebook = submission.attachments?.find(
        f => f.filename.endsWith('.ipynb')
      );

      if (!notebook) return null; // skip ungraded

      return {
        rubricAssessment: { "_8027": { points: 100 } }
        // No `comment` here on purpose -- see Safety Rule 6. Add one only when
        // the instructor asked for written feedback, and make it feedback.
      };
    }
  });
`)
```

Use `search_canvas_tools("grading", "signatures")` to discover available TypeScript modules and their function signatures before writing code.

## Token Efficiency

The three strategies have very different token costs:

| Strategy | When | Token Cost | Why |
|----------|------|------------|-----|
| `grade_with_rubric` | 1-9 submissions | Low | Few round-trips, small payloads |
| `bulk_grade_submissions` | Multiple submissions, any supported size | Medium | Bounded calls with batch data |
| `execute_typescript` | Enabled, authorized custom logic | Workload-dependent | Grading logic runs locally; only the code and selected output need to enter model context |

The key insight: as submission count grows, sending grading logic to the server can use less model context than bringing all submission data into the conversation.

## Safety Rules

1. **Validate substantive payloads.** Use `dry_run: true` for each new bulk payload; review it and reuse unchanged validation when still valid. Keep callbacks side-effect free and revalidate current targets before sending.
2. **Verify the rubric before grading.** Confirm criterion IDs, point ranges, and rating IDs match the assignment rubric. Use every criterion, including zero scores. Partial assessments can be written and then reported unconfirmed; inspect Canvas before retrying.
3. **Qualify changed integrations.** A new or materially changed adapter/installed scope may need a bounded canary under the same publication authority. Do not require live test writes before every unchanged batch. Read back actual approved deliveries.
4. **Respect rate limits.** Use `max_concurrent: 5` and `rate_limit_delay: 1.0` (1 second between batches). Canvas rate limits are approximately 700 requests per 10 minutes.
5. **Use actual instructor authority.** Retain required teacher acceptance of final academic results and authorization for exact publication effects. Reuse valid approval across unchanged approved rows/batches. Ask only for missing authority or a substantive change; do not repeat plan and payload approval as separate ceremonies.
6. **Never attach a comment the instructor did not ask for.** A submission comment is visible to the student in SpeedGrader, it *appends* on every call rather than replacing, and it cannot be un-sent. "Assign grade 8" means the grade only. Never generate a comment that restates the grade or narrates that grading happened (e.g. "Graded via automated review") — that reads to the student as a bot mark on their work and carries no feedback. Include a comment only when the instructor asked for written feedback, and then make it feedback about the work.

## Example Prompts

- "Grade Assignment 5 using the rubric"
- "Show me the rubric for the midterm project and grade all submissions"
- "Bulk grade all ungraded submissions for Assignment 3 -- give full marks on criterion 1 and 80% on criterion 2"
- "How many submissions still need grading for the final paper?"
- "Dry run bulk grading for Assignment 7 so I can review before submitting"
- "Use code execution to grade all 150 homework submissions with custom logic"

## Error Recovery

| Error | Cause | Action |
|-------|-------|--------|
| 401 Unauthorized | Token expired or invalid | Inspect the affected authorized connection and use its supported renewal path; continue independent work |
| 403 Forbidden | Not an instructor/TA for this course | Verify Canvas role |
| 404 Not Found | Wrong course, assignment, or rubric ID | Re-check IDs with `list_assignments` or `list_rubrics` |
| 422 Unprocessable | Invalid rubric assessment format | Verify criterion IDs and point ranges match the rubric |
| Partial failures in bulk | Some grades submitted, others failed | Check each status. Unconfirmed assessments may already be saved: inspect Canvas before retrying to avoid duplicate comments. Retry only confirmed unsaved failures |
