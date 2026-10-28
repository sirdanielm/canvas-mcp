# Common Issues and Solutions


Code execution is off by default and requires its feature/write gates. Each
`execute_typescript` run has privileged Canvas access and can bypass MCP previews
and content fencing. Follow the [execution prerequisites](bulk_grading_example.md#execution-and-approval-requirements)
and existing scope authorization; an unavailable tool is an operator boundary.
Quick fixes for the most common problems with Canvas MCP.

## Installation Issues

### "canvas-mcp-server: command not found"

**Problem**: The CLI command isn't available after installation.

**Solution**:
```bash
# Make sure you installed with the editable flag
uv pip install -e .

# Or reinstall
pip uninstall canvas-mcp
uv pip install -e .

# Verify it worked
canvas-mcp-server --help
```

### "No module named 'canvas_mcp'"

**Problem**: Package not installed correctly.

**Solution**:
```bash
# Navigate to the canvas-mcp directory
cd /path/to/canvas-mcp

# Install in editable mode
uv pip install -e .
```

## Configuration Issues

### "Authentication failed"

**Problem**: Canvas API token is invalid or expired.

**Solution**:
1. Identify the exact connection and distinguish rejected authentication (401)
   from permission for the requested action (403).
2. Follow the institution's supported renewal or permission process. Preserve the
   existing credential until an authorized replacement is verified; do not change
   accounts or broaden grants to bypass a hold.
3. Use the owning launcher's credential path. SDM launchers validate a proposed
   Keychain replacement before storing it; a generic `.env` edit is not their setup.
4. Reconnect only the affected idle connection through its supported lifecycle.
   Preserve active operations and previews; a restart can invalidate process-bound
   tokens. See [worker recovery](../docs/sdm-gradebook-worker.md#coordination-and-crash-recovery).

Institutional token lifetimes vary. A previous successful connection is not
evidence that its credential or permissions remain valid now.

### "Canvas API URL is invalid"

**Problem**: Wrong URL format in `.env`.

**Solution**:
Your Canvas API URL should look like:
```bash
CANVAS_API_URL=https://your-institution.instructure.com/api/v1
```

HTTPS bare-host and trailing-slash URLs are normalized to `/api/v1`; explicit
API versions are preserved. Include `https://`; a missing scheme is invalid.

Test with:
```bash
canvas-mcp-server --test
```

### "Cannot create access token"

**Problem**: Your institution restricts self-service API token creation. The "New Access
Token" button is missing or errors out. At some schools this applies to students only; at
others it applies to everyone, instructors included.

**Solution**:
First check whether your institution has a token request form — search its IT knowledge
base for "Canvas API token". If it does, that form is the only path; the Canvas UI will
keep refusing.

**University of Illinois Urbana-Champaign**: use the
[Canvas API Token Request form](https://help.uillinois.edu/TDClient/42/UIUC/Requests/TicketRequests/NewForm?ID=4AZBjiZfXWs_&RequestorType=Service).
After approval, activate the token under **Account → Settings → Approved Integrations**,
then retrieve its value from the U of I Box link Technology Services sends you. Illinois
tokens expire after 30 days as of August 2026
([KB 150325](https://answers.uillinois.edu/illinois/internal/150325)).

Otherwise, contact your Canvas administrator or IT help desk:
```
Hi, I'm trying to use the Canvas API to track my assignments
and grades. Could you help me create an API access token or
enable API access for my account?
```

Most institutions will enable this for legitimate educational purposes.

## Runtime Issues

### "Rate limit exceeded (429 errors)"

**Problem**: Making too many API requests too quickly.

**Good news**: Canvas MCP now automatically handles rate limiting!

**What happens**:
- Canvas MCP detects rate limit errors
- Automatically waits and retries (up to 3 times)
- Shows progress: "⏳ Rate limited (429). Retrying in 4s..."

**If it still fails**:
- For a read, use the transport's supported bounded backoff; retain incomplete
  results as incomplete.
- For a possible write, inspect the original operation and independent readback.
  A timeout does not prove nothing was sent; never blindly repeat a grade,
  comment, message or content mutation.
- Code execution is not a throttling workaround and does not inherit the
  gradebook publisher's durable recovery contracts.

### "Tool not showing up in Claude Desktop"

**Problem**: Canvas MCP tools aren't available in Claude.

**Solution**:

1. **Check your MCP client's configuration file**:
   
   **Claude Desktop** (macOS): `~/Library/Application Support/Claude/claude_desktop_config.json`
   **Claude Desktop** (Windows): `%APPDATA%\Claude\claude_desktop_config.json`
   **Cursor** (macOS/Linux): `~/.cursor/mcp_config.json`
   **Windsurf** (macOS): `~/Library/Application Support/Windsurf/mcp_config.json`
   **Zed**: Settings → Open Settings (`settings.json`)
   
   Ensure it contains:
   ```json
   {
     "mcpServers": {
       "canvas-api": {
         "command": "canvas-mcp-server"
       }
     }
   }
   ```
   
   Or for Zed:
   ```json
   {
     "context_servers": {
       "canvas-api": {
         "command": {
           "path": "/absolute/path/to/canvas-mcp-server",
           "args": []
         }
       }
     }
   }
   ```

2. **Reconnect the affected connection when idle**:
   - Preserve active or uncertain operations and inspect their owner/status first
   - Use supported reconnect without restarting unrelated shared services
   - Missing tools may be deliberate role, feature or allowlist policy

3. **Check for errors**:
   - For Claude Desktop: Look in the developer console
   - For other clients: Check client logs or developer console
   - Or run manually: `canvas-mcp-server` and check for errors

### "Data seems outdated"

**Problem**: Seeing old information.

**Solution**:
Course-ID mappings remain in the process cache; `CACHE_TTL` does not currently
expire those mappings. Assignment reads fetch Canvas directly. Waiting five minutes
is not a supported freshness remedy. Inspect the exact response and configured
course identity before considering an authorized, idle service restart.

## Data Issues

### "Student names showing as Student_xxxxxxxx"

**This is working correctly!** If you have anonymization enabled:

```bash
ENABLE_DATA_ANONYMIZATION=true
```

This supports FERPA-conscious workflows by reducing identity data before tool output reaches the AI client. It does not by itself establish compliance.

**To disable** (only after reviewing your institution's privacy requirements):
```bash
ENABLE_DATA_ANONYMIZATION=false
```

Then restart your MCP client.

### "Missing some courses or assignments"

**Problem**: Not all data is showing up.

**Possible causes**:

1. **Canvas permissions**: Your API token might not have access to all courses
   - Solution: Check your Canvas role and permissions

2. **Archived courses**: Old courses might be archived
   - Solution: Verify concluded-course scope and access; changing course state needs authorization for that action

3. **Pagination issue**: Very large datasets might not load completely
   - Solution: Inspect pagination errors and exact scope; a narrower successful query does not prove the original inventory complete

## Performance Issues

### "Bulk operations are very slow"

**Problem**: Grading or analyzing large datasets takes too long.

**Solution**: Choose the qualified interface for the actual operation. For SDM
score/comment delivery, use the [immutable batch workflow](../docs/sdm-gradebook-workflow.md#immutable-batch-authorization)
with exact manifest approval, bounded dispatch and independent channel readback.
Generic code execution has separate role, write and transport controls; it does
not inherit the publisher's source/QC checks or durable operation history.
Do not switch interfaces to bypass throttling, approval or an uncertain result.
Processing time and token use depend on the actual workload and selected output.

### "AI assistant seems to get confused with lots of data"

**Problem**: Too much data in context.

**Solution**:
- Be specific about what you want
- Use filters (course names, assignment IDs, date ranges)
- For large operations, use code execution to keep data out of your AI assistant's context

Example:
```
Show me students who haven't submitted Assignment 3 in CS 101
```
Instead of:
```
Show me all students and all their submissions
```

## Integration Issues

### "Works in terminal but not in MCP client"

**Problem**: `canvas-mcp-server` works manually but not through your MCP client.

**Solution**:

1. **Check the command path**:
   ```bash
   which canvas-mcp-server
   ```

2. **Use full path in config** if needed:
   
   For Claude Desktop, Cursor, Windsurf, Continue:
   ```json
   {
     "mcpServers": {
       "canvas-api": {
         "command": "/full/path/to/canvas-mcp-server"
       }
     }
   }
   ```
   
   For Zed:
   ```json
   {
     "context_servers": {
       "canvas-api": {
         "command": {
           "path": "/full/path/to/canvas-mcp-server",
           "args": []
         }
       }
     }
   }
   ```

3. **Check environment variables**: Your MCP client might not have access to your `.env`
   - Make sure `.env` is in the canvas-mcp directory
   - Or set `CANVAS_API_TOKEN` and `CANVAS_API_URL` as system environment variables

## Getting More Help

1. **Read supported stderr warnings/errors.** `DEBUG` and `LOG_API_REQUESTS` are
   parsed but do not enable request logging in the current implementation: its
   logger is INFO and request messages are DEBUG. Redact output before sharing.

2. **Test the connection**:
   ```bash
   canvas-mcp-server --test
   ```

3. **Check the logs**: Run the server manually to see error messages

4. **Still stuck?**
   - [Open an issue](https://github.com/vishalsachdev/canvas-mcp/issues)
   - Include:
     - Error messages (redact your API token!)
     - Your Canvas instance URL (e.g., "your-institution.instructure.com")
     - What you were trying to do
     - Output from `canvas-mcp-server --test`

## Quick Diagnostic Checklist

Run through this list:

- [ ] `.env` file exists and has `CANVAS_API_TOKEN` and `CANVAS_API_URL`
- [ ] Canvas API token is valid (test in Canvas web UI)
- [ ] `canvas-mcp-server --test` succeeds
- [ ] Claude Desktop config includes canvas-mcp
- [ ] Restarted Claude Desktop after config changes
- [ ] Canvas API URL includes HTTPS and identifies the intended institution

If all these pass and it still doesn't work, [open an issue](https://github.com/vishalsachdev/canvas-mcp/issues)!
