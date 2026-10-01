# Security Policy

## Reporting Security Vulnerabilities

We take the security of Canvas MCP seriously. If you discover a security vulnerability, please follow these guidelines:

### Reporting Process

**DO NOT** open a public GitHub issue for security vulnerabilities. Instead:

1. **Email**: Send details to the maintainer at the email listed in the repository
2. **GitHub Security Advisory**: Use [GitHub's Security Advisory feature](https://github.com/vishalsachdev/canvas-mcp/security/advisories/new) (preferred)

### What to Include

Please provide:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Varies based on severity
  - Critical: 1-7 days
  - High: 7-14 days
  - Medium: 14-30 days
  - Low: Best effort

---

## Implemented security boundaries

Checked against the implementation on 2026-10-01. These controls reduce specific
risks; they do not certify an entire deployment or establish FERPA compliance.

### Credentials and transport

- Canvas access depends on the issued token's grants and the account's Canvas
  permissions. Canvas MCP cannot expand or rewrite those grants. Treat a token
  as a credential that may expose sensitive records and permit consequential
  writes; use the minimum authority appropriate to the task.
- The standard stdio server reads credentials from its process environment
  (optionally loaded from a restricted `.env`). Keep credentials out of Git,
  logs and chat. The SDM launchers instead retrieve the Canvas token from macOS
  Keychain; see [the local workflow](docs/sdm-gradebook-workflow.md). They are
  separate from the generic overlay token-storage placeholders.
- HTTP supports an `MCP_ACCESS_KEYS` gate or explicitly configured external
  authentication. The Entra path trusts platform-injected identity only when
  a correctly configured authenticator fronts the endpoint; it checks that
  identity against the configured/approved access records. The app cannot prove
  that the external authenticator is present. Do not expose a bypassable backend.
- HTTP requests carry each caller's `X-Canvas-Token`; the Canvas API URL is
  server-pinned. Startup rejects a server-wide `CANVAS_API_TOKEN` in HTTP mode
  and refuses an unconfigured access gate unless the operator explicitly opts
  into external authentication. Stdio relies on the local process boundary.
- Cleartext Canvas URLs are rejected, not upgraded. The only opt-in exception
  is an explicit loopback development URL with `CANVAS_ALLOW_INSECURE_HTTP=true`.
  Protect the HTTP MCP endpoint with TLS at its serving/authentication boundary.
- Revoke exposed or unused tokens and follow institutional credential-rotation
  policy. Never publish tokens or raw student data in security reports.

### Tool availability and human approval

`ALLOWED_WRITE_TOOLS` controls which side-effect tools are registered. Unset
means read-only on HTTP and preserves existing registered tools on stdio.
An empty value or `none` removes side-effect tools; an explicit list admits
only those names. `all` excludes code execution. Registration feature gates
still apply. A missing tool is an operator boundary, not permission to bypass it.

Confirmation tokens bind a preview to the requested operation and current
state; they do not prove human approval. Tool access, Canvas authority, teacher
approval and publication verification are distinct requirements. Untrusted
Canvas text is fenced by supported read tools but remains untrusted data.
See [the agent guide](AGENTS.md#operator-write-policy).

### Code execution

`execute_typescript` is off by default (`EXECUTE_TYPESCRIPT_ENABLED=false`),
including the supplied Docker/Azure deployment defaults. An enforced write
allowlist must explicitly name it; `all` does not enable it. HTTP execution,
if deliberately enabled, requires a working container sandbox and the caller's
request credentials; local/unsandboxed execution is refused on HTTP.

When enabled, code receives a Canvas token and can make immediate writes without
preview/confirmation tokens, read anonymization or untrusted-content fencing.
Review each execution as a privileged Canvas operation. The allowlist controls
tool registration; it does not constrain arbitrary Canvas calls made by code.

In stdio, `TS_SANDBOX_MODE=auto` can fall back to local execution when container
support is unavailable. Local execution has process/environment/resource
limits, not complete filesystem, process or network isolation. The Node-level
network guard is best effort and bypassable; a container alone does not turn
its hostname allowlist into strong egress enforcement. See
[upstream issue 157](https://github.com/vishalsachdev/canvas-mcp/issues/157).
The default requested execution timeout is 120 seconds and may be capped by
server sandbox limits; timeouts do not undo writes that already happened.

### Privacy and local exports

The central Canvas client applies endpoint-specific identity masking when
`ENABLE_DATA_ANONYMIZATION` is enabled (default true). Supported names use
hash-derived labels such as `Student_a8f7e23d`; supported email fields are
pseudonymized and operational Canvas IDs remain available. These are
pseudonyms, not a guarantee of anonymity. Free text, submissions, grades,
course content and exempt profile/content fields can remain sensitive.

Generic MCP labels do not satisfy the SDM permanent four-digit PIN policy.
Use the authenticated registry-bound mapping for explicitly authorized local
copies, preserve originals, and hold missing/conflicting identities. A private
PIN archive is still student data. See [PIN policy](docs/STUDENT-PIN-POLICY.md),
[private export validation](docs/local-pin-exports.md) and
[post-QC archive gates](docs/post-qc-pin-archives.md).

### Errors, retries and audit evidence

The client applies request timeouts and bounded 429 backoff, including supported
`Retry-After` values. Those controls do not make every write safe to retry.
For an uncertain write, inspect durable state and independent readback before
retrying; never infer failure merely from a timeout or lost response.

Validation, URL sanitization and error handling reduce accidental exposure but
do not guarantee that every error or diagnostic is free of sensitive material.
Inspect and redact logs before sharing; do not dump tokens, student records or
raw API responses into public issues. Keep private operational receipts outside
Git and website upload roots. The SDM gradebook publisher has separate preview,
explicit-enable and durable readback controls; general MCP logging is not a
substitute for those receipts.

## Remaining limitations

- Local stdio trust and external HTTP authentication must be enforced by the
  operator's actual deployment, not by a configuration label.
- Arbitrary code execution remains a privileged escape from tool-level preview
  and privacy guarantees; strict egress isolation is not implemented by the
  Node guard.
- Placeholder overlay flags do not provide generic key storage, mTLS, SIEM
  forwarding or day-based retention. Supported structured redaction and optional
  access/execution audit events are implemented; they do not guarantee complete
  redaction or a durable grade-delivery ledger. See [overlay status](config/overlays/README.md).
- Rate limits, account permissions and token grants remain subject to Canvas;
  optional masking and local workflow gates do not establish institutional compliance.

---

## Compliance

### FERPA Considerations

Canvas MCP provides technical controls that can support FERPA-regulated workflows. Compliance depends on the full institutional deployment and operating process:

1. Enable data anonymization: `ENABLE_DATA_ANONYMIZATION=true`
2. Review privacy settings before using AI tools
3. Ensure your Canvas deployment and AI provider meet your institution's requirements
4. Follow your institution's data handling policies

### Canvas API Terms of Service

Users must comply with:
- Canvas API Terms of Service
- Your Canvas instance's acceptable use policy
- Your institution's data handling requirements

---

## Security Contact

For security concerns:
- **GitHub Security Advisory**: [Create Advisory](https://github.com/vishalsachdev/canvas-mcp/security/advisories/new) (preferred)
- **Email**: See repository contact information

**Please do not open public issues for security vulnerabilities.**

---

*Last reviewed against implementation: October 1, 2026*
