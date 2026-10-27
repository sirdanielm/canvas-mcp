---
name: canvas-course-builder
description: Scaffold complete Canvas LMS course structures from specs, templates, or existing courses. Creates modules, pages, assignments, and discussions in bulk. Use when asked to "build a course", "scaffold modules", "create course structure", "set up a new course", or "copy course structure".
---

# Canvas Course Builder

Build complete Canvas course structures from a natural language description, a JSON template, or by cloning an existing course. Creates modules with pages, assignments, discussions, and proper organization in one workflow.

## Prerequisites

- **Canvas MCP server** must be running and connected.
- Authenticated user must have **instructor or designer role** in the target course.
- Target course must already exist in Canvas (this skill populates it, does not create the course itself).

## Modes

This skill operates in three modes:

### Mode 1: Build from Spec (default)
The user describes the course structure in natural language or provides a structured spec.

### Mode 2: Build from Template
Load a saved JSON template to scaffold a course.

### Mode 3: Clone from Existing Course
Read the structure of Course A and replicate it into Course B.

## Steps

### 1. Determine Mode and Gather Input

Reuse the mode, course, specification and template already supplied in the request or current task. Resolve exact course IDs with tools. Ask only for missing information that materially blocks the build; do not repeat an interview for a complete specification. When the mode itself is genuinely unspecified, offer:

> How would you like to build the course structure?
> 1. **Describe it** -- Tell me the structure (e.g., "15 weeks, each with an overview page, assignment, and discussion")
> 2. **From template** -- Load a saved template file
> 3. **Clone another course** -- Copy structure from an existing course

**For Mode 1 (Spec):** Resolve from the request; ask only for essential missing fields:
- Target course (code or ID)
- Number of modules/weeks/units
- Module naming pattern (e.g., "Week N: [Topic]")
- Standard items per module (overview page, assignment, discussion, etc.)
- Any module-specific variations (midterm week, final project, etc.)

**For Mode 2 (Template):** Reuse the selected template or resolve its path; parse it. Ask only when the template remains ambiguous.

**For Mode 3 (Clone):** Resolve the supplied source/target and read the source:
- Source course (code or ID)
- Target course (code or ID)
- Call `get_course_structure(source_course)` to read the full structure

### 2. Generate Structure Preview

Read `get_course_structure(target_course)` and reconcile the requested structure with existing objects before planning any create. Reuse recorded IDs and matching existing objects, distinguish exact matches from substantive conflicts, and create only missing objects. Do not deduplicate by title alone when several plausible targets exist.

Build a concise preview of the remaining work. Present it when useful; it is not another approval gate for an already-authorized build:

```
## Course Build Plan: [Course Name]

### Structure: 15 modules x 4 items each = 60 items total

| Module | Page | Assignment | Discussion | SubHeader |
|--------|------|------------|------------|-----------|
| Week 1: Introduction | Overview | HW 1 (10 pts) | Week 1 Forum | Materials |
| Week 2: Fundamentals | Overview | HW 2 (10 pts) | Week 2 Forum | Materials |
| ... | ... | ... | ... | ... |
| Week 14: Review | Overview | -- | Review Forum | Materials |
| Week 15: Final | Overview | Final Project (100 pts) | -- | Materials |

### Items to create:
- 15 modules
- 15 overview pages
- 14 assignments
- 14 discussion topics
- 15 subheaders
- Total: 73 Canvas objects

```

### 3. Resolve Only Consequential Missing Decisions

Proceed with a complete authorized specification, including requested unpublished assembly. Make reversible implementation choices independently. Ask only about an unresolved target/content decision or a publication effect outside the existing authorization. Reuse valid approval for unchanged scope; actual tool/platform confirmation requirements still apply.

### 4. Execute Creation

Create items in dependency order:

1. **Modules first:** Call `create_module` with `published=false` for each module (modules default to unpublished)
2. **Pages:** Call `create_page` with `published=false` for each overview page (pages default to published)
3. **Assignments:** Call `create_assignment` for each assignment (unpublished)
4. **Discussions:** Defer creation until publication is authorized. `create_discussion_topic` publishes immediately unless `delayed_post_at` defers visibility; draft creation is unavailable.
5. **Module items:** Reuse existing links; call `add_module_item` only for missing links, passing the intended `published` state explicitly. Read back each linked object and final module visibility.

Track actual created counts and deferred discussions separately. The example
below assumes discussion publication was explicitly authorized:
```
Creating modules... 15/15 done
Creating pages... 15/15 done
Creating assignments... 14/14 done
Creating discussions... 14/14 done
Linking items to modules... 58/58 done
```

Record created IDs and completed links as work succeeds. On an uncertain response, inspect target state before retrying; an error is not proof that creation failed. Hold only affected objects/dependencies and continue independent items. Resume at the first unfinished object instead of rebuilding the course. Verify final structure, order and publication states against the requested specification.

### 5. Report Results

```
## Build Complete: [Course Name]

### Created:
- 15 modules
- 15 overview pages
- 14 assignments
- 14 discussion topics
- 58 module items linked

### Failed (0):
None

### Next Steps:
- Verify modules, pages and assignments remained unpublished as requested; discussion creation requires separate publication scope
- Add content to overview pages
- Set due dates on assignments
- Run `/canvas-course-qc` to verify structure
```

### 6. Save as Template (Optional)

Save a template when requested or already included in the task. Otherwise finish with the build result; template creation is not a prerequisite. Use `get_course_structure(target_course)` for the saved structure.

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `list_courses` | Find available courses |
| `get_course_structure` | Read source course for cloning; verify after build |
| `create_module` | Create each module |
| `create_page` | Create overview/content pages |
| `create_assignment` | Create assignments |
| `create_discussion_topic` | Create discussion forums |
| `add_module_item` | Link items to modules |
| `update_module` | Publish modules when ready |

## Template Format

Templates are JSON files with this structure:

```json
{
  "template_name": "Standard 15-Week Semester",
  "modules": [
    {
      "name_pattern": "Week {n}: {topic}",
      "items": [
        {"type": "SubHeader", "title_pattern": "Week {n} Materials"},
        {"type": "Page", "title_pattern": "Week {n} Overview"},
        {"type": "Assignment", "title_pattern": "HW {n}", "points": 10},
        {"type": "Discussion", "title_pattern": "Week {n} Discussion"}
      ]
    }
  ],
  "special_modules": [
    {"position": 8, "name": "Midterm Review", "items": [{"type": "Page", "title": "Midterm Study Guide"}]},
    {"position": 15, "name": "Final Project", "items": [{"type": "Assignment", "title": "Final Project", "points": 100}]}
  ]
}
```

## Example

**User:** "Build a 15-week structure for BADM 350 with a weekly overview page, homework, and discussion"

**Agent:** Resolves the target, inventories existing objects and creates missing authorized drafts. Discussions are deferred unless their visibility is authorized.

**User:** "Clone the structure from CS 101 into CS 102"

**Agent:** Reads source and target structures, reuses matching objects, creates missing unpublished objects and verifies the resulting structure. It asks only about substantive conflicts or unauthorized publication.

## Notes

- Modules default to unpublished; pages default to published. Pass `published=false` explicitly for drafts. `create_assignment` defaults to unpublished. `create_discussion_topic` always publishes on creation; if students must not see a discussion yet, schedule it with `delayed_post_at` instead of creating it now.
- Content is **not** copied when cloning -- only structure (module names, item types, organization).
- To copy content (not just structure) between courses, use `create_content_migration` (preview + confirmation token) and poll `get_content_migration_status`; per-page copy via `get_page_content` + `create_page` suits a few pages.
- Run `canvas-course-qc` after building to verify the structure is complete and consistent.
