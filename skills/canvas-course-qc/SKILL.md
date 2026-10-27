---
name: canvas-course-qc
description: Learning designer quality check for Canvas LMS courses. Audits module structure, content completeness, publishing state, date consistency, and rubric coverage. Use when asked to "QC a course", "is this course ready", "pre-semester check", or "quality review".
---

# Canvas Course QC

Automated quality checklist for Learning Designers to verify a Canvas course is ready for students. Runs structure, content, publishing, and completeness checks — then reports issues by priority.

## Prerequisites

- **Canvas MCP server** must be running and connected.
- Authenticated user must have **instructor, TA, or designer role** in the target course.
- Best run before the semester starts or before publishing a course to students.

## Steps

### 1. Identify Target Course

Reuse the course and intended state from the request/current task. Resolve exact IDs with tools; ask only if ambiguous. Distinguish draft assembly from student-ready publication; default an unspecified QC request to read-only inspection.

If not specified, prompt:

> Which course would you like to quality-check?

Use `list_courses` to look up available courses if needed.

### 2. Retrieve Course Structure

Call `get_course_structure(course_identifier)` to get the full module-to-items tree in one call.

This returns all modules with their items, publishing states, and summary statistics.

### 3. Run Structure Checks

Analyze the module tree for structural issues:

| Check | Priority | What to Look For |
|-------|----------|------------------|
| Empty modules | Warning | Modules with 0 items (confusing to students) |
| Naming consistency | Suggestion | Do all modules follow the same pattern? (e.g., "Week N:", "Unit N:") |
| Module count | Suggestion | Does it match expected count for course length? |
| Item ordering | Suggestion | SubHeaders present for organization? |

### 4. Run Content Checks

Call `list_assignments(course_identifier)` and check each assignment:

| Check | Priority | What to Look For |
|-------|----------|------------------|
| Missing due dates | Depends on intended state | Block only when the requested release requires dates; drafts may intentionally omit them |
| Missing descriptions | Warning | Assignments with empty or null description |
| Missing points | Warning | Assignments without points_possible set |
| Date sequencing | Warning | Due dates that don't follow module order |
| Rubric coverage | Suggestion | Graded assignments without an associated rubric |

`list_assignments` supplies IDs, names, due dates and points; fetch
`get_assignment_details` for descriptions/settings and `get_rubric` with the
assignment ID for rubric coverage. Structure metadata cannot flag empty page
bodies: use `get_page_content` for the pages in scope.

### 5. Run Publishing Checks

Using the structure data:

| Check | Priority | What to Look For |
|-------|----------|------------------|
| Visibility mismatch | Depends on intended state | Compare module, item and linked-object visibility independently; an unpublished module does not guarantee linked content is inaccessible elsewhere |
| Unpublished modules | Expected for drafts | Flag only a mismatch with the explicitly intended publication state |
| No front page | Warning | Course has no front page set |

`list_pages` renders a `(Front Page)` text marker. Use `get_front_page` to verify
the current front page rather than expecting a `front_page` Boolean in that output.

### 6. Run Completeness Checks

Compare module structures to find inconsistencies:

| Check | Priority | What to Look For |
|-------|----------|------------------|
| Inconsistent structure | Warning | Most modules have 4 items but some only have 1 |
| Missing item types | Suggestion | Most modules have an Assignment but some don't |

Build a "typical module" profile from the most common item-type pattern, then flag modules that deviate.

### 7. Generate QC Report

Present results grouped by priority:

```
## Course QC Report: [Course Name]

### Summary
- Modules: 15 | Items: 67 | Assignments: 15 | Pages: 20
- Issues found: 3 blocking, 5 warnings, 2 suggestions

### Blocking Issues (fix before publishing)
1. Assignment "Final Project" has no due date
2. "Week 5 Quiz" is published although this unit was requested as an unpublished draft
3. Assignment "Midterm" has no due date

### Warnings (should fix)
1. 2 empty modules: "Week 14", "Week 15"
2. 3 assignments missing descriptions: HW 3, HW 7, HW 12
3. No front page set for course
4. Due dates out of order: Week 8 assignment due before Week 7
5. "Week 3" module has 1 item while typical modules have 4

### Suggestions (nice-to-have)
1. Module naming: 13/15 use "Week N:" pattern but "Midterm Review" and "Final Review" don't
2. 5 graded assignments have no rubric attached
```

### 8. Offer Follow-up Actions

Report actionable mismatches against the requested state. If repairs were already authorized, apply unambiguous in-scope fixes and verify them; otherwise provide the concrete proposed repair set. Do not propose publishing every unpublished module as a generic repair. Publish only the exact authorized set and verify the container, children and linked objects. Reuse one valid authorization across its unchanged bounded batches while preserving actual tool confirmations. Accessibility checks and further courses are optional, not prerequisites.

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `list_courses` | Find available courses |
| `get_course_structure` | Full module tree with items |
| `list_assignments` | Assignment details for content checks |
| `get_assignment_details` | Deep-dive on flagged assignments |
| `list_pages` | Check for front page |
| `get_page_content` | Verify pages have content |
| `list_rubrics` | Check rubric coverage |
| `update_module` | Auto-fix: publish modules |
| `bulk_update_pages` | Auto-fix: publish pages |

## Example

**User:** "QC check for BADM 350"

**Agent:** Runs all checks, outputs the prioritized report.

**User:** "Fix the publishing issues"

**Agent:** Resolves the exact intended publication set and existing authority, applies only those changes, and verifies child/linked-object visibility. Intentional drafts remain unpublished.

## Notes

- This skill is designed for **Learning Designers** who manage course structure before students access it.
- Run this before each semester or after major content updates.
- Pairs well with `canvas-accessibility-auditor` for comprehensive course review.
