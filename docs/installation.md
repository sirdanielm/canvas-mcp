# Local MCP installation

This guide configures the main Canvas MCP server. The [gradebook worker](sdm-gradebook-worker.md)
and [authoring connection](sdm-canvas-authoring-workflow.md) have separate setup.
Use Python 3.11+, an MCP-compatible client and an institution-authorized Canvas
token. Private tokens and student data do not belong in Git or support logs.

## Source installation

From the checkout you intend to run:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp env.template .env
```

Put your own HTTPS Canvas origin ending in `/api/v1` and token in `.env`:

```dotenv
CANVAS_API_URL=https://canvas.example.edu/api/v1
CANVAS_API_TOKEN=replace-with-your-private-token
```

Canvas commonly provides token creation under Account → Settings. Where the
institution disables self-service, follow its IT token request process. Token
expiry and renewal depend on that institution; do not infer them from an old
setup example. A 401/403 is an authentication/permission hold, not permission to
substitute another account.

Local SDM launchers retrieve credentials from macOS Keychain and require the
`local-keychain` extra. Follow their specific guide instead of moving secrets into
client configuration or replacing an already installed connection.

## Client configuration

Use the absolute virtualenv binary path and a working directory that can resolve
your private `.env`. Client formats vary; these examples are for local stdio.

### JSON-based MCP clients

For a client supporting the `mcpServers` format:

```json
{
  "mcpServers": {
    "canvas-api": {
      "command": "/absolute/path/to/canvas-mcp/.venv/bin/canvas-mcp-server",
      "cwd": "/absolute/path/to/canvas-mcp"
    }
  }
}
```

If your client does not support `cwd`, use its supported environment/configuration
mechanism to make the private credentials available. Do not rely on shell PATH
shims or copy a different client's configuration format without checking it.
On Windows, use the virtualenv's `Scripts\canvas-mcp-server.exe` path.

### Codex

Add one table to `~/.codex/config.toml`, using your existing connection name if
already configured:

```toml
[mcp_servers.canvas-api]
command = "/absolute/path/to/canvas-mcp/.venv/bin/canvas-mcp-server"
cwd = "/absolute/path/to/canvas-mcp"
```

`codex mcp list` checks registration. Restart/reconnect only your own client after
changing its configuration; do not blindly restart a shared server that may have
another writer. The standard connection does not configure the separate
`canvas-gradebook` server.

### Packaged desktop extension

Upstream [releases](https://github.com/vishalsachdev/canvas-mcp/releases) provide
`canvas-mcp.mcpb` for Claude Desktop. Install it through that client's extension
UI and enter the institution's `/api/v1` URL and your token when prompted.
Packaged upstream code and this fork's unreleased source can differ; a successful
extension installation does not install SDM gradebook/workbook overlays.

## Verification

In the intended source environment:

```bash
canvas-mcp-server --test
canvas-mcp-server --config
```

The first checks the Canvas connection. The second displays configuration; keep
its output private if it includes sensitive settings. Inspect the client's
available tools after reconnecting. Role profiles and feature/operator gates
change the registered tool set.

## Permission defaults and troubleshooting

- `CANVAS_ROLE` selects student, educator or all tools; it does not increase
  Canvas permissions.
- `ALLOWED_WRITE_TOOLS` controls main-server side effects. Unset HTTP is read-only;
  stdio retains configured tools. `none` removes writes. Disabled tools are
  boundaries, not invitations to use direct requests.
- `execute_typescript` is off by default and requires separate privileged-action
  authorization when enabled.
- The public hosted endpoint is retired. Authenticated self-hosting uses
  per-request Canvas tokens and its own access gate; follow
  [deployment guidance](../deploy/azure/), including its startup restrictions.
- For startup errors, check Python version, binary path, dependency environment
  and working directory. For 401/403, resolve the authorized token/permission
  issue. For throttling, retain bounded backoff and the operation's uncertainty
  rules. Report aggregate error classes, never raw student responses or tokens.

Use [AGENTS.md](../AGENTS.md) and the [tool reference](../tools/README.md) for exact
confirmation contracts. Earlier client-specific examples are retained in the
[pre-trim installation section](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/README.md#local-installation).
