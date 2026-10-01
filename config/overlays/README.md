# Configuration overlays

These files are configuration examples, not implemented security tiers. Copying
an overlay does not certify a deployment or enable controls that the server
does not read. Status below was checked against source on 2026-10-01; the `.env`
files themselves retain historical comments and placeholder values.

## Applying an example

Review [env.template](../../env.template) and the target launcher's actual
configuration path first. Apply one overlay through the environment manager used
by that process, verify its effective settings, and record the configuration
revision. Standard stdio can load a restricted `.env`; the SDM launchers use
macOS Keychain for the Canvas token. Do not copy secrets into source control.

| Example | Intended use | Limits |
|---|---|---|
| `baseline.env` | Sandbox resource and privacy defaults | No guaranteed localhost binding or complete egress isolation |
| `public.env` | Local workstation configuration | Keyring/envelope flags are placeholders; the network flag is not a blanket outbound deny |
| `enterprise.env` | Institutional configuration planning | Client-auth, secret-store, retention and SIEM flags here do not implement those services |

## Implemented controls and placeholders

- **Transport:** the server supports stdio and `streamable-http`. `MCP_BIND_HOST`
  and `MCP_BIND_PORT` in these overlays are not read by the server. HTTP binding
  uses `--host` and `--port` (defaults `0.0.0.0` and `8819`); stdio has no socket
  binding. An overlay's localhost value therefore does not secure an HTTP bind.
- **HTTP authentication:** implemented controls are `MCP_ACCESS_KEYS` and the
  explicitly configured external-auth/Entra path described in `env.template`
  and [Azure deployment guidance](../../deploy/azure/README.md). The overlay's
  `MCP_CLIENT_AUTH_MODE`, API-key-required and certificate-authority fields do
  not wire up API-key or mTLS authentication.
- **Write policy:** `ALLOWED_WRITE_TOOLS` is implemented; HTTP is read-only when
  unset. Code execution is separately off by default and must be explicitly
  enabled and admitted by an enforced allowlist. None of these overlays is
  permission to grade, send messages or publish to Canvas.
- **Sandbox:** resource limits and the Node network guard are implemented.
  `TS_SANDBOX_MODE=auto` can fall back to local execution on stdio; HTTP refuses
  non-container execution. The Canvas host is added to the guarded allowlist,
  and the Node guard is best effort, not strict egress isolation. Container
  availability does not establish a strong host allowlist boundary.
- **Privacy:** `ENABLE_DATA_ANONYMIZATION` is implemented for supported client
  responses. It does not scrub every free-text field or create permanent SDM
  PIN archives. See [security and privacy boundaries](../../SECURITY.md).
- **Logging:** `LOG_REDACT_PII` masks supported structured context fields.
  `LOG_ACCESS_EVENTS` and `LOG_EXECUTION_EVENTS` enable implemented audit events;
  `AUDIT_LOG_DIR` selects their local directory. The audit implementation uses
  size-based rotation (10 MiB, five backups), not the overlay's day-based policy.
  These controls do not guarantee every free-text diagnostic is scrubbed.
- **Unwired declarations:** token-backend/envelope settings, `LOG_ROTATION_DAYS`,
  `LOG_RETENTION_DAYS`, `LOG_DESTINATION`, SIEM forwarding and firewall hints do
  not enforce their advertised policies. The SDM Keychain launcher is a separate
  implementation, not evidence that generic token-backend flags work.

## Verification

Use the repository's reviewed-PR and applicable CI policy for every change;
security findings are not merely advisory for a tier called "Baseline".
Validate the effective transport, credential source, tool inventory and relevant
failure behavior using controlled tests. Do not enable code execution, live
writes, paid model runs or publication merely to test an overlay. Preserve
private configuration and receipts outside Git and the website upload root.
