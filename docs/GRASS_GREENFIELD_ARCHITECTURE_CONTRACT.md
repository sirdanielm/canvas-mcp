# GrAss architecture contract

The canonical GrAss architecture and shared local implementation are maintained in
[LocalGrAss](https://github.com/sirdanielm/LocalGrAss).

Start with this repository's [grading flow](goals-and-status.md#grading-flow)
and [integration boundaries](grass-workflow-integration.md): Canvas and
teacher-folder/paper intake produce paired score/feedback proposals through local
tools and teacher review. The revision-bound transfer into central EDIT remains
a separate integration; source tests do not establish that complete path.

- [Architecture contract](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md)
- [Implementation plan](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_NEXT_BUILD_PLAN.md)
- [Production connection plan](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/PRODUCTION_CONNECTION_PLAN.md)
- [Implementation status](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/IMPLEMENTATION_STATUS.md)
- [Local goals and ownership](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/SDM-GOALS-AND-WORK-STATUS.md)

Shared local tooling is developed in LocalGrAss; Canvas-specific services,
policies and installed targets remain owned by this repository. Quinn/local AI
is an optional future adapter. Teacher approval, publication releases and
verified Canvas readback remain separate requirements.

Original design transfers, frozen comparison versions and operator checkpoints
are preserved in the operator's private archive. They are historical evidence;
edit the canonical LocalGrAss contract for current design work.

See the [documentation map](documentation-map.md) for current Canvas operator
guides and the distinction between implementation, installed runtime and live
publication authority.

The Canvas-owned [capture contract](grass-capture-contract.md) defines the exact
observation/PIN handoff to the local core. Receipt, local teacher login and
fake-release tests do not connect the general accepted-pair release bridge.
Existing guarded Canvas delivery remains a separate capability.
