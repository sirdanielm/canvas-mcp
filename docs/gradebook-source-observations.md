# Gradebook source observations

The optional source sidecar records limited submission metadata alongside an
unchanged gradebook snapshot. It is private: its cell keys and artifact IDs can
identify students and must be handled like the snapshot. Nothing is stored unless
an authorized caller explicitly requests and saves it. Existing snapshot
consumers are unchanged.

Every observation remains held. A reported Canvas attempt or attachment is not
proof of currentness, source bytes or a relationship to a downstream Drive file.
Unsupported submission types and incomplete, ambiguous or multi-artifact cases
stay held. No scan, grading or publication authority follows from a sidecar.

The store binds a bounded sidecar envelope to an existing snapshot digest.
`REFERENCE_UNKNOWN` means no reference was supplied and does not establish
absence. `SNAPSHOT_ID_MISMATCH_UNVALIDATED` means only that snapshot IDs differ:
the referenced snapshot and observation have not been validated. `INCOMPLETE`
includes missing, malformed and incomplete evidence. `HELD` describes a
structurally complete observation, not a current or approved source.

Reference ownership, atomic publication of a reference, orphan discovery,
retention and recovery are not implemented. An interrupted write can leave an
orphan; do not infer absence, adopt or delete it based on filename or time. Agree
on a bounded private reconciliation procedure before integrating a consumer.
Local file and directory synchronization does not by itself prove durability
across power loss or every filesystem. Existing private store trust boundaries
still apply.
