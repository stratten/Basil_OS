"""A tiny MCP server that speaks over standard input and output, for the stdio transport tests.

Run it with the Python that runs the tests. It needs no network and no account. The environment variable FIXTURE_PID_FILE, when set, receives the server's process id so a test can prove the process is gone afterwards.
"""

import os
import time

from mcp.server.fastmcp import FastMCP

server = FastMCP("basil-stdio-fixture")

_pid_file = os.environ.get("FIXTURE_PID_FILE")
if _pid_file:
    with open(_pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


@server.tool()
def echo(text: str) -> str:
    """Return the text it was given."""
    return f"echo: {text}"


@server.tool()
def where_am_i() -> str:
    """Return the working directory and the FIXTURE_GREETING environment variable."""
    return f"{os.getcwd()}|{os.environ.get('FIXTURE_GREETING', '')}"


@server.tool()
def sleep_forever() -> str:
    """Never answers, so a test can prove the deadline stops the process."""
    time.sleep(3600)
    return "unreachable"


if __name__ == "__main__":
    server.run(transport="stdio")
