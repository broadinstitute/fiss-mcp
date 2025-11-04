# Terra.Bio MCP Server

[![Tests](https://github.com/broadinstitute/fiss-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/broadinstitute/fiss-mcp/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/broadinstitute/fiss-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/broadinstitute/fiss-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that enables Claude and Claude Code to interact with [Terra.Bio](https://terra.bio) workspaces via the [FISS (Firecloud) API](https://github.com/broadinstitute/fiss).

## Features

### Phase 1: Read-Only Tools ✅ COMPLETED

- **`list_workspaces`** - List all Terra workspaces accessible to the authenticated user
- **`get_workspace_data_tables`** - List data tables (entity types) in a workspace with row counts
- **`get_submission_status`** - Get detailed status of workflow submissions (supports customizable workflow limits)
- **`get_job_metadata`** - Get Cromwell metadata for specific workflows with optional filtering
- **`get_workflow_logs`** - Get workflow logs with optional GCS content fetching and smart truncation

### Phase 2: Monitoring Tools ✅ COMPLETED

- **`list_submissions`** - List all workflow submissions in a workspace with status and metadata
- **`get_workflow_outputs`** - Get output files and values from completed workflows
- **`get_workflow_cost`** - Get cost information for workflow executions

## Use Cases

- **WDL Pipeline Development**: Monitor Terra workflow runs while developing and debugging WDL pipelines with Claude Code
- **Regression Testing**: Run automated tests against benchmark datasets on Terra
- **Job Monitoring**: Track submission status, interpret logs, and debug workflow failures

## Installation

### Prerequisites

- Python 3.10 or higher
- Google credentials configured for Terra.Bio access (via FISS)
- Terra.Bio account with workspace access

### Setup

1. Clone this repository:
```bash
git clone <repository-url>
cd fiss-mcp
```

2. Install dependencies:

**Note**: The `firecloud` package requires special installation due to setuptools compatibility ([fiss#192](https://github.com/broadinstitute/fiss/issues/192)):

```bash
# Install setuptools<80 first (required for firecloud)
pip install "setuptools<80"

# Install all dependencies with --no-build-isolation
pip install --no-build-isolation -r requirements.txt
```

For development (includes test dependencies):
```bash
# Install setuptools<80 first (required for firecloud)
pip install "setuptools<80"

# Install all dependencies with --no-build-isolation
pip install --no-build-isolation -r requirements.txt

# Install additional test/development dependencies
pip install pytest-cov ruff
```

3. Verify your Google credentials are configured for FISS:
```python
from firecloud import api as fapi
response = fapi.list_workspaces()
print(response.status_code)  # Should be 200
```

## Usage

### Running the Server (Development)

Test the server in development mode with detailed logging:

```bash
fastmcp dev src/terra_mcp/server.py
```

This starts an interactive development session where you can test tools.

### Running the Server (Production)

Run the server with stdio transport (for Claude Desktop integration):

```bash
fastmcp run src/terra_mcp/server.py
```

Or run directly:

```bash
python src/terra_mcp/server.py
```

### Claude Desktop Integration

To use this MCP server with Claude Desktop, add the following to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "terra": {
      "command": "python",
      "args": ["-m", "fastmcp", "run", "/absolute/path/to/fiss-mcp/src/terra_mcp/server.py"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/your/credentials.json"
      }
    }
  }
}
```

Replace `/absolute/path/to/fiss-mcp` with the actual path to your cloned repository.

After updating the configuration, restart Claude Desktop.

### Example Usage in Claude

Once configured, you can interact with Terra.Bio through Claude:

```
Human: List all my Terra workspaces

Claude: I'll list your accessible Terra workspaces.
[Claude calls list_workspaces tool]
You have access to 3 workspaces:
1. broad-firecloud-testing/demo-workspace (created by user@broad.io on 2024-01-15)
2. my-billing/analysis-workspace (created by user@broad.io on 2024-02-01)
...```

**Human**: Show me the data tables in my analysis workspace

**Claude**: I'll retrieve the data tables from your analysis workspace.
[Claude calls get_workspace_data_tables with namespace="my-billing", name="analysis-workspace"]
The workspace has 2 data tables:
- participants: 150 rows
- samples: 450 rows
```

**Human**: Check the status of submission abc-123-def

**Claude**: I'll check the status of that submission.
[Claude calls get_submission_status with submission_id="abc-123-def"]
Submission abc-123-def is currently Running with 10 workflows:
- Succeeded: 7 workflows
- Running: 2 workflows
- Failed: 1 workflow
```

**Human**: Can you fetch the logs for the failed workflow and help me debug it?

**Claude**: I'll fetch the stderr logs for the failed workflow.
[Claude calls get_workflow_logs with workflow_id="wf-789", fetch_content=True]
The task "AlignReads" failed with this error at the end of the log:
```
OutOfMemoryError: Java heap space
  at htsjdk.samtools.BAMRecordCodec.decode()
```
This is a memory issue. The task needs more RAM allocated. You can increase the memory in your WDL using the runtime attribute: `memory: "32 GB"`
```

## Testing

Run the test suite to verify the server implementation:

```bash
# Install dependencies (if not already installed)
pip install "setuptools<80"
pip install --no-build-isolation -r requirements.txt
pip install pytest-cov

# Run tests
PYTHONPATH=src pytest tests/ -v

# Run with coverage
PYTHONPATH=src pytest tests/ --cov=src/terra_mcp --cov-report=term
```

The test suite includes:
- Server initialization verification
- Tool registration checks (all 8 tools: 5 Phase 1 + 3 Phase 2)
- Mocked FISS API responses
- Mocked GCS log fetching and truncation
- Error handling scenarios (404s, 403s, API failures, GCS errors)
- Parameter validation (max_workflows, include_keys, fetch_content, truncate, etc.)
- Helper function tests (truncation logic, GCS URL parsing)
- Phase 2 tool tests (submissions listing, outputs retrieval, cost fetching)

## Development

### Project Structure

```
fiss-mcp/
├── src/terra_mcp/
│   ├── __init__.py          # Package initialization
│   └── server.py            # MCP server implementation
├── tests/
│   └── test_server.py       # Test suite
├── requirements.txt         # Dependencies
├── pyproject.toml          # Project configuration
├── CLAUDE.md               # Project specification
└── README.md               # This file
```

### Adding New Tools

To add new tools (Phase 2 or Phase 3 from CLAUDE.md):

1. Add the tool function in `src/terra_mcp/server.py`
2. Use the `@mcp.tool()` decorator
3. Add comprehensive docstrings (visible to LLMs)
4. Use `Annotated` type hints for parameter descriptions
5. Implement two-tier error handling (ToolError for user-facing errors)
6. Add tests in `tests/test_server.py`

Example:
```python
@mcp.tool()
async def my_new_tool(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    ctx: Context,
) -> dict[str, Any]:
    """Tool description that LLMs will see.
    
    Detailed description of what this tool does.
    
    Args:
        workspace_namespace: Description
        workspace_name: Description
        
    Returns:
        Dictionary with result data
    """
    try:
        ctx.info("Starting operation")
        # Implementation
        return {"result": "data"}
    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Error: {e}")
        raise ToolError("User-friendly error message")
```

## Roadmap

See [CLAUDE.md](CLAUDE.md) for the complete implementation plan.

### Phase 1: Read-Only Tools ✅ COMPLETED
- [x] `list_workspaces`
- [x] `get_workspace_data_tables`
- [x] `get_submission_status` (with optional workflow limit)
- [x] `get_job_metadata` (with optional metadata filtering)
- [x] `get_workflow_logs` (with optional GCS content fetching and smart truncation)

### Phase 2: Monitoring Tools ✅ COMPLETED
- [x] `list_submissions`
- [x] `get_workflow_outputs`
- [x] `get_workflow_cost`

### Phase 3: Write Operations
- [ ] `upload_data_to_table`
- [ ] `submit_workflow`
- [ ] `abort_submission`

## Architecture

### Design Principles

1. **Explicit workspace identification**: Always require namespace + name (no implicit "current workspace")
2. **Actionable error messages**: All errors provide clear next steps for LLMs
3. **Smart log truncation**: For error logs, return tail (last ~25K chars) where failures appear
4. **Two-tier error handling**: ToolError for expected failures, masked exceptions for internal errors

### Key Dependencies

- **FastMCP**: Python framework for building MCP servers
- **FISS (firecloud)**: Python client for Terra.Bio API
- **google-cloud-storage**: For fetching workflow logs from GCS
- **Pydantic**: Data validation and schema generation

## Troubleshooting

### "Failed to list workspaces" error

Ensure your Google credentials are properly configured:

```bash
# Check if gcloud is authenticated
gcloud auth list

# Or verify GOOGLE_APPLICATION_CREDENTIALS is set
echo $GOOGLE_APPLICATION_CREDENTIALS
```

### Tools not appearing in Claude Desktop

1. Verify the MCP server is configured in `claude_desktop_config.json`
2. Check the absolute path to `server.py` is correct
3. Restart Claude Desktop completely
4. Check Claude Desktop logs: `~/Library/Logs/Claude/mcp*.log` (macOS)

### Import errors when running server

Make sure you've installed all dependencies:

```bash
pip install -r requirements.txt
```

Or install the package in editable mode:

```bash
pip install -e .
```

## Contributing

Contributions are welcome! Areas for improvement:

- Additional Phase 2 and Phase 3 tools (see CLAUDE.md)
- Enhanced error handling and retry logic
- WDL parsing and validation integration
- Workflow cost analysis tools
- Call-caching information parsing

## License

See [LICENSE](LICENSE) file for details.

## Resources

- [Model Context Protocol Specification](https://modelcontextprotocol.io)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [FISS Python Library](https://github.com/broadinstitute/fiss)
- [Terra.Bio Platform](https://terra.bio)
- [WDL Specification](https://github.com/openwdl/wdl)
