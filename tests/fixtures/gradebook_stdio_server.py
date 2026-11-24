"""Run the production gradebook MCP registry against a fictional destination."""

import sys
from pathlib import Path

if __name__ == "__main__":
    # Run this checkout even when the test interpreter has another editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from gradebook_stdio_destination import COURSES, ORIGIN, Destination

    from canvas_mcp.gradebook.client import GradebookClient
    from canvas_mcp.gradebook.server import create_server
    from canvas_mcp.gradebook.store import Store

    destination = Destination(Path(sys.argv[1]))
    client = GradebookClient(ORIGIN, "fictional", transport=destination.transport())
    server = create_server(
        client,
        Store(Path(sys.argv[2])),
        COURSES,
        enable_push=True,
        enable_comments=True,
    )
    server.run(transport="stdio")
