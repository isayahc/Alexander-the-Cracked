"""Console entry point: run the Obvious MCP bridge under uvicorn."""

from __future__ import annotations

import os

import uvicorn

DEFAULT_PORT = 8899


def main() -> None:
    port = int(os.environ.get("BRIDGE_PORT", str(DEFAULT_PORT)))
    uvicorn.run("obvious_mcp_bridge.server:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
