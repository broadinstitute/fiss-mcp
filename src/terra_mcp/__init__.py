"""Terra.Bio MCP Server Package

MCP server for interacting with Terra.Bio workspaces via the FISS API.

Deliberately imports nothing: `server.py` imports `terra_mcp.gcs`, so an eager
`from terra_mcp.server import mcp` here would make a script launch
(`python .../server.py`, which the Claude Science launcher uses) load the module
twice, once as `__main__` and once as `terra_mcp.server`. That gives two FastMCP
instances, two skills providers, and an imported copy whose ALLOW_WRITES never
sees the command-line flag. Import `terra_mcp.server` directly if you need it.
"""

__version__ = "2.0.0"
