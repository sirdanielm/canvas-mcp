# Focused dependency repair

The project requires `joserfc>=1.7.5,<2` and locks 1.7.5. The explicit floor
also protects fresh installations that do not consume `uv.lock`.

The maintainer's [issuer-validation advisory](https://github.com/authlib/joserfc/security/advisories/GHSA-r74j-q665-7rpj)
affects versions through 1.7.2 and is patched in 1.7.3. The
[JWS allocation advisory](https://github.com/authlib/joserfc/security/advisories/GHSA-9pg5-8c7x-5hfx)
affects versions through 1.7.4 and is patched in 1.7.5. The selected release
supports Python 3.10 or newer and the retained cryptography dependency.

The candidate also backports upstream
[`f6c71e1`](https://github.com/vishalsachdev/canvas-mcp/commit/f6c71e15aac0df7be56899c1edc0cd5438357d97),
which changes only the `multidict` lock block from 6.7.1 to 6.9.1. The remaining
upstream changes are outside this focused repair. Fork extras and development
groups remain intact; no security ignore or CI policy is added.

An isolated environment built from the frozen all-extras lock passed 2,733
Python tests with 21 skips, Ruff and mypy. The frozen export's dependency audit
checked 98 resolved packages and reported no known vulnerabilities under the
existing CI policy. Offline smoke checks accepted a valid string issuer,
rejected an array-valued issuer, and rejected an oversized three-segment JWS.
Hosted CI checks the exact published candidate separately.

The reviewed [reference allocation limits](gradebook-reference-limits.md)
have independent synthetic boundary coverage. Source promotion is separate from
installation, service reload, deployment and authorization for live operations.
