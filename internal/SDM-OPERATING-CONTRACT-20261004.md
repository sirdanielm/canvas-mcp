# October 4 SDM operating contract

**Recorded:** 2026-10-04 19:11:46 EDT. Documentation-only reconciliation prepared from the current user decisions, canonical source closeout and qualified owner receipts. Review/publication of this document is separate from any live operation.

**Audience:** repository operators. This tracked reference sits outside the manual website upload root; `internal/` does not make Git content private.

## Repository responsibility

canvas-mcp owns authenticated Canvas reads, the gradebook mirror/permanent PIN authority and separately gated score/comment delivery. Use the [gradebook workflow](../docs/sdm-gradebook-workflow.md), [worker runbook](../docs/sdm-gradebook-worker.md) and [GrAss integration boundaries](../docs/grass-workflow-integration.md) for existing mechanics. October 4 comment source is merged but capability stays off. Reviewed GET repair installation is separate from durable source integration `61ec2e`; this record does not restart GET, release a queue or enable any comment/score writer. Manual marks must become exact literal points through a reviewed private plan before delivery.

## Teacher policy decisions and implementation boundary

The following October 4 decisions govern the intended grading workflow. Verify the exact source/runtime and approved payload before claiming the policy is implemented or applying it.

| Evidence path | Teacher decision | Required qualification |
| --- | --- | --- |
| Complete validated itemized formative pipeline result | 100% participation, regardless of analytical percentage | Preserve detailed analytical/item scores and feedback; verify assignment/source/attempt identity |
| Itemized pipeline failed | 50% actual-score floor | Correct assignment and participation; at least 50% of assigned questions attempted overall, at least 50% model confidence; inspect every required student-response page |
| Other failed submissions | Corrective comment and dashboard review; no new score | Comments require their separately enabled capability, reviewed payload and delivery receipt |

Exclude instruction/reference pages and pages unassigned to that course. There is no per-page attempted-percentage threshold. Clear missing work deducts points and finishes the grade; do not invent deduction weights or treat image uncertainty as a demonstrated blank/missing response. Confirmed-absence zero is a separate qualification: applicable/due work, no Canvas submission and complete manual evidence of absence. Missing scans, failed reads and a blank checklist cell are not absence proof.

Unit 1 summative remains rigorous item scoring: Core raw/40 × 100; Advanced raw/48 × 100. Retain raw earned/possible points, item/LI feedback, wrong item, deduction, percentage-point effect and reassessment needs. Summative bad scans go to the teacher's rescan queue only, without student bad-image comments. Teacher acceptance and final Canvas push remain separate from any model result or proposal import.

Manual marks: a plain check means full participation; an explicit circled minus means half credit; blank means no inferred zero. Deduplicate repeated PDFs/margins and preserve exact student/assignment/source joins. Three B4 plain-check/circled-minus conflicts remain held. The reported manual candidate `34e5ba6` and its 100-row plan are under independent review and **unapplied**; older preview totals are provisional, not current applied scores.

## Dated source and operational facts

These are owner-reported or receipt-verified checkpoints, not a live monitor. None is authority to rerun a grader or republish a student record.

- Unit 1 admitted provider work is terminal, with **38 current canonical pairs**. All **167 active source files** have exact recorded result/hold accounting. Saved-pair availability **130** and **37 hold-only** is a separate overlapping view; do not add it to the canonical batch or historical selection. Unpaid source-reading triage and teacher rescans/checks continue. Historical provisional pairs retain their qualifications.
- Central state remains **64 proposal rows**, with **195 history rows**, **44 formulas** and **22 teacher-input rows**. The **498 numeric + 29 EX** Edit baseline is preserved. Three approved additions were verified; the expanded test import and remaining qualified/manual writes are still pending exact authority. Task 32 owns proposal/history durability. A saved pair is not necessarily staged, accepted or delivered.
- All fifteen registered assignment graders were installed and independently verified at source `853d5e8` / runtime `2cef` (330 file-equality checks). All eleven Unit 1 setup seals, including 1.4a, are complete. GrAssCI is a separate profile. Source/setup equality is not completed grading or future-grader readiness.
- The existing Unit 2 sequence runs **2.1.2 → 2.1.3 → 2.2.2** under its fleet owner. **2.1.1 is excluded**, preserving its old stopped cursor. Keep installed `853d5e8` / runtime `2cef`, source, configuration, cursors and controls frozen during it; Canvas/OCR are closed at the latest owner checkpoint. No duplicate dispatch or deployment.

## Publication, installation and delivery holds

| Artifact | Dated disposition |
| --- | --- |
| GrAss percentage `2711453` | Frozen; source publication and expanded test import still pending exact authority |
| Durable GET source integration `61ec2e` | Unpublished, approval-pending; installed reviewed repair is separately retained |
| Unsent-comment correction `0aee0e` | Unpublished, approval-pending |
| Required-work policy `bf3e85d3d2e37920a57648d3aa7d418a890d397b` | Source-only accepted; unpublished/undeployed; 2.1.1 amendment held |
| Native16 adapter `061975a` | Integration pending |
| Manual `34e5ba6` / 100-row plan | Independent review; unapplied; three B4 conflicts held |

The reviewed GET repair is the installed two-file `55c4` / runtime `719b` overlay. GrAss PR150 and canvas-mcp PR17 are merged source, with **comment capability off**; this does not prove delivered comments. Tool 6 PR22 is merged and its selected installed engine/README update has separate readback/offline proof. No live Safe Sync was run by closeout. Local saved-history installation, old 17-file/V1 bundles and the separate nightly patch remain held.

Separate authorized LitSim work may proceed in its isolated LocalGrAss lane while idle, with grading prioritized. It is not an installed or accepted production feature. Preserve its owned files and the manual/fleet owners' source paths. Other lanes require their own exact scope.

Daniel controls the evening teacher review and Canvas push. Verify accepted score/comment payload, current source/attempt identity, target/destination and actual response/readback before delivery. Source publication, central import and a successful GET refresh each establish different facts. This document enables no capability and starts no worker, refresh, grader, provider call or Canvas write.

## Evidence and preservation

Keep student names/PINs, images, financial/teacher payloads, source files, credentials, private receipts and mutable live IDs outside Git. Public documentation records only safe policy, aggregate states and source revisions. Use the existing private registry and permanent-PIN exporter for authorized derived copies; never invent identities or alter protected originals.

The nine-repo closeout verified current canonical heads/accepted merge trees and retained original dirty/pinned work. Nightly audit remains completed with exceptions (seven lost-stderr Git read failures and stale top-level October 3 delivery summary); the later bounded inventory had zero Git read failures. No scheduler rerun or repair is implied. Retain dated receipts and history; exact current source and live readbacks must be verified before a separately authorized mutation.
