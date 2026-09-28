# Gradebook visibility reads

The central reader fetches each published graded assignment's complete
`/courses/:course_id/assignments/:assignment_id/submissions` response with
`include[]=visibility`. It no longer reads submission cells from the course-wide
`/students/submissions` endpoint. Each cell's score, attempt, excusal and visibility
come from the same exact-assignment response; false and unknown visibility remain
false and unknown. There is no inversion, optimistic default or merged fallback.

This avoids an upstream course-wide visibility lookup defect observed in
[Canvas's controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/submissions_api_controller.rb)
and [visibility service](https://github.com/instructure/canvas-lms/blob/master/app/services/assignment_visibility/assignment_visibility_service.rb)
on September 28, 2026: the controller looks up a user ID in a mapping keyed by
assignment ID. This source finding does not establish any institution's deployed
Canvas revision. Archived responses remain immutable evidence of what was read.

Reads stay sequential, GET-only and paginated with the existing same-origin,
same-endpoint and repeated-page checks. Course identity, assignment ownership,
submission assignment identity and duplicate targets are checked before returning
a snapshot. Canonical normalization still excludes inactive students and leaves
missing cells absent. The private artifact store receives a snapshot only after
all reads and validation complete; errors never promote a partial result.

One 120-second deadline covers the entire snapshot, including discovery,
pagination and existing rate-limit backoff. At most 100 published graded
assignments may be read. The current classroom workload of roughly 18 assignments
and 120 students is well below that cap; the deadline bounds latency when a
provider stalls or paginates unexpectedly. Reaching either limit preserves the
previous snapshot and requires investigation rather than automatic partial
continuation. These limits do not change publication authorization or its separate
fresh exact-target preflight.

Fictional transport regressions cover conflicting bulk/exact visibility,
true/false/unknown values, pagination, inactive users, target mismatch, duplicate
records, incomplete reads, deadline failure and unchanged prior artifacts.
