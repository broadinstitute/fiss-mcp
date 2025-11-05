# Terra.Bio MCP Server

[![Tests](https://github.com/broadinstitute/fiss-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/broadinstitute/fiss-mcp/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/broadinstitute/fiss-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/broadinstitute/fiss-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that enables Claude and Claude Code to interact with [Terra.Bio](https://terra.bio) workspaces via the [FISS (Firecloud) API](https://github.com/broadinstitute/fiss).

## Available Tools

This MCP server provides 15 tools for interacting with Terra.Bio workspaces:

### Workspace & Data Discovery

- **`list_workspaces`** - List all Terra workspaces accessible to the authenticated user
- **`get_workspace_data_tables`** - List data tables (entity types) in a workspace with row counts
- **`get_entities`** - Read entity data from Terra data tables for workflow inputs

### Workflow Monitoring & Status

- **`list_submissions`** - List all workflow submissions in a workspace with status and metadata
- **`get_submission_status`** - Get detailed status of workflow submissions (supports customizable workflow limits)
- **`get_job_metadata`** - Get Cromwell metadata for specific workflows with optional filtering
- **`get_workflow_logs`** - Get workflow logs with optional GCS content fetching and smart truncation
- **`get_workflow_outputs`** - Get output files and values from completed workflows
- **`get_workflow_cost`** - Get cost information for workflow executions

### Workflow Configuration & Management

- **`get_method_config`** - Get method configuration details including WDL version and input/output mappings
- **`update_method_config`** - Update method configuration (e.g., change WDL version to match development branch)
- **`copy_method_config`** - Create copies of method configurations for testing or development
- **`submit_workflow`** - Launch WDL workflows for single entities or batch processing
- **`abort_submission`** - Cancel running workflow submissions

### Data Management

- **`upload_entities`** - Upload or update entity data in Terra data tables with validation

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
      "command": "python3",
      "args": ["/absolute/path/to/fiss-mcp/src/terra_mcp/server.py"]
    }
  }
}
```

Replace `/absolute/path/to/fiss-mcp` with the actual path to your cloned repository.

**Note**: If you installed dependencies in a Python virtual environment, replace `python3` with the absolute path to your venv's Python interpreter (e.g., `/absolute/path/to/venv/bin/python3`).

**Note**: If you haven't authenticated with Google Cloud locally, you may need to add credentials:
```json
{
  "mcpServers": {
    "terra": {
      "command": "python3",
      "args": ["/absolute/path/to/fiss-mcp/src/terra_mcp/server.py"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/your/credentials.json"
      }
    }
  }
}
```

After updating the configuration, restart Claude Desktop.

### Claude Code Integration

To use this MCP server with Claude Code, run the following command from your terminal:

```bash
claude mcp add terra --type stdio \
  --command python3 \
  --arg /absolute/path/to/fiss-mcp/src/terra_mcp/server.py
```

Replace `/absolute/path/to/fiss-mcp` with the actual path to your cloned repository.

**Note**: If you installed dependencies in a Python virtual environment, use the absolute path to your venv's Python interpreter instead of `python3`:

```bash
claude mcp add terra --type stdio \
  --command /absolute/path/to/venv/bin/python3 \
  --arg /absolute/path/to/fiss-mcp/src/terra_mcp/server.py
```

If you need to specify Google Cloud credentials:

```bash
claude mcp add terra --type stdio \
  --command python3 \
  --arg /absolute/path/to/fiss-mcp/src/terra_mcp/server.py \
  --env GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/credentials.json
```

To verify the server is connected:
```bash
claude mcp list
```

To reconnect after code changes:
```bash
claude mcp reconnect terra
```

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
- Tool registration checks (all 15 tools)
- Mocked FISS API responses
- Mocked GCS log fetching and truncation
- Error handling scenarios (404s, 403s, 400s, 409s, API failures, GCS errors)
- Parameter validation (max_workflows, include_keys, fetch_content, truncate, expression, entity_data, etc.)
- Helper function tests (truncation logic, GCS URL parsing)
- Coverage for all tool categories: workspace discovery, monitoring, workflow management, and data management

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

To extend the server with additional Terra.Bio functionality:

1. Add the tool function in `src/terra_mcp/server.py`
2. Use the `@mcp.tool()` decorator
3. Add comprehensive docstrings (visible to LLMs)
4. Use `Annotated` type hints for parameter descriptions
5. Implement two-tier error handling (ToolError for user-facing errors)
6. Add tests in `tests/test_server.py` following TDD principles

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

## Future Enhancements

Potential areas for expansion (see [CLAUDE.md](CLAUDE.md) for details):

- **Workflow Analysis**: Automatic cost optimization suggestions, call-caching analysis
- **Enhanced Error Handling**: Automatic retry logic for transient failures, rate limit backoff
- **WDL Integration**: WDL parsing, validation, and linting integration
- **Batch Operations**: Bulk entity operations, workspace cloning
- **Terra Notebooks**: Integration with Terra notebook operations
- **Advanced Filtering**: Enhanced entity queries with complex filters and pagination

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

Contributions are welcome! Please ensure:

- Follow the established code patterns and architecture
- Write tests before implementing features (TDD)
- Maintain comprehensive error handling
- Add clear documentation for LLM consumption
- Run tests and linting before submitting PRs

## License

See [LICENSE](LICENSE) file for details.

## Resources

- [Model Context Protocol Specification](https://modelcontextprotocol.io)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [FISS Python Library](https://github.com/broadinstitute/fiss)
- [Terra.Bio Platform](https://terra.bio)
- [WDL Specification](https://github.com/openwdl/wdl)
