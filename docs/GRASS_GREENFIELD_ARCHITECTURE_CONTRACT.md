# GrAss architecture contract

The canonical GrAss design and new implementation are maintained in
[LocalGrAss](https://github.com/sirdanielm/LocalGrAss).

- [Architecture contract](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md)
- [Implementation plan](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_NEXT_BUILD_PLAN.md)
- [Production connection plan](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/PRODUCTION_CONNECTION_PLAN.md)
- [Receipt/review build](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/PILOT_CONNECTIONS_2026-10-01.md)
- [Implementation status](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/IMPLEMENTATION_STATUS.md)
- [Local tooling ownership](https://github.com/sirdanielm/LocalGrAss)

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
observation/PIN handoff to the local core. Its new receipt, local teacher login
and fake release tests do not establish a live policy scorer or publisher.
