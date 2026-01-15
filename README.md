# Terra.Bio MCP Server

[![Tests](https://github.com/broadinstitute/fiss-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/broadinstitute/fiss-mcp/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/broadinstitute/fiss-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/broadinstitute/fiss-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that enables Claude and Claude Code to interact with [Terra.Bio](https://terra.bio) workspaces via the [FISS (Firecloud) API](https://github.com/broadinstitute/fiss).

## Table of Contents

- [Available Tools](#available-tools)
  - [Read-Only Tools (Always Available)](#read-only-tools-always-available)
  - [Write-Access Tools (Require --allow-writes Flag)](#write-access-tools-require---allow-writes-flag)
- [Use Cases](#use-cases)
  - [Example Usage](#example-usage)
- [Data Privacy and Security Considerations](#data-privacy-and-security-considerations)
- [Installation](#installation)
- [Usage](#usage)
  - [Running the Server (Development)](#running-the-server-development)
  - [Running the Server (Production)](#running-the-server-production)
  - [Claude Desktop Integration](#claude-desktop-integration)
  - [Claude Code Integration](#claude-code-integration)
- [Testing](#testing)
- [Development](#development)
  - [Project Structure](#project-structure)
  - [Adding New Tools](#adding-new-tools)
- [Future Enhancements](#future-enhancements)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Resources](#resources)

## Available Tools

This MCP server provides 16 tools for interacting with Terra.Bio workspaces:

### Read-Only Tools (Always Available)

These tools are available in both read-only mode (default) and when write access is enabled:

#### Workspace & Data Discovery

- **`list_workspaces`** - List all Terra workspaces accessible to the authenticated user
- **`get_workspace_data_tables`** - List data tables (entity types) in a workspace with row counts
- **`get_entities`** - Read entity data from Terra data tables for workflow inputs

#### Workflow Monitoring & Status

- **`list_submissions`** - List all workflow submissions in a workspace with status and metadata
- **`get_submission_status`** - Get detailed status of workflow submissions (supports customizable workflow limits)
- **`get_job_metadata`** - Get Cromwell metadata for specific workflows with optional filtering
- **`get_workflow_logs`** - Get workflow logs with optional GCS content fetching and smart truncation
- **`get_workflow_outputs`** - Get output files and values from completed workflows
- **`get_workflow_cost`** - Get cost information for workflow executions
- **`get_batch_job_status`** - Debug infrastructure failures (docker pull errors, preemption, OOM) via Google Batch API

#### Workflow Configuration (Read-Only)

- **`get_method_config`** - Get method configuration details including WDL version and input/output mappings

### Write-Access Tools (Require `--allow-writes` Flag)

⚠️ **These tools require write access to be enabled.** By default, the server runs in read-only mode for safety. To use these tools, you must start the server with the `--allow-writes` flag (see integration sections below).

#### Workflow Configuration Management

- **`update_method_config`** - Update method configuration (e.g., change WDL version to match development branch)
- **`copy_method_config`** - Create copies of method configurations for testing or development

#### Workflow Execution Control

- **`submit_workflow`** - Launch WDL workflows for single entities or batch processing
- **`abort_submission`** - Cancel running workflow submissions

#### Data Management

- **`upload_entities`** - Upload or update entity data in Terra data tables with validation

## Use Cases

- **WDL Pipeline Development**: Monitor Terra workflow runs while developing and debugging WDL pipelines with Claude Code
- **Regression Testing**: Run automated tests against benchmark datasets on Terra
- **Job Monitoring**: Track submission status, interpret logs, and debug workflow failures

### Example Usage

Once configured, you can interact with Terra.Bio through Claude:

```
Human: List all my Terra workspaces

Claude: I'll list your accessible Terra workspaces.
[Claude calls list_workspaces tool]
You have access to 3 workspaces:
1. broad-firecloud-testing/demo-workspace (created by user@broad.io on 2024-01-15)
2. my-billing/analysis-workspace (created by user@broad.io on 2024-02-01)
...
```

```
Human: Show me the data tables in my analysis workspace

Claude: I'll retrieve the data tables from your analysis workspace.
[Claude calls get_workspace_data_tables with namespace="my-billing", name="analysis-workspace"]
The workspace has 2 data tables:
- participants: 150 rows
- samples: 450 rows
```

```
Human: Check the status of submission abc-123-def

Claude: I'll check the status of that submission.
[Claude calls get_submission_status with submission_id="abc-123-def"]
Submission abc-123-def is currently Running with 10 workflows:
- Succeeded: 7 workflows
- Running: 2 workflows
- Failed: 1 workflow
```

```
Human: Can you fetch the logs for the failed workflow and help me debug it?

Claude: I'll fetch the stderr logs for the failed workflow.
[Claude calls get_workflow_logs with workflow_id="wf-789", fetch_content=True]
The task "AlignReads" failed with this error at the end of the log:
```
OutOfMemoryError: Java heap space
  at htsjdk.samtools.BAMRecordCodec.decode()
```
This is a memory issue. The task needs more RAM allocated. You can increase the memory in your WDL using the runtime attribute: `memory: "32 GB"`
```

```
Human: I have a large submission running as the most recent submission in workspace my_lab/my_workspace.
Can you summarize where each workflow is in the pipeline?

Claude: I'll check the submission status and analyze the running workflows.
[Claude calls list_submissions with namespace="my_lab", name="my_workspace", limit=1]
[Claude calls get_submission_status with submission_id="abc-123-def"]
[Claude calls get_job_metadata for running workflows to identify current task]

Submission abc-123-def has 500 workflows with this breakdown:
- Succeeded: 312 workflows (complete)
- Running: 156 workflows
  - 45 in "align_reads" (earliest stage)
  - 78 in "call_variants" (middle stage)
  - 33 in "annotate_vcf" (final stage)
- Failed: 12 workflows (see next for details)
- Queued: 20 workflows (waiting to start)

The running workflows are progressing normally through the pipeline.
```

```
Human: My submission had 32 workflow failures. Can you categorize what went wrong?

Claude: I'll analyze the failed workflows to identify failure patterns.
[Claude calls get_submission_status to identify failed workflow IDs]
[Claude calls get_job_metadata (summary mode) for each failed workflow]
[Claude calls get_batch_job_status for infrastructure failures]

Failure Analysis for 32 failed workflows:

| Category | Count | Root Cause |
|----------|-------|------------|
| OOM errors | 19 | call_variants task exceeded 16GB memory limit |
| Disk exhaustion | 10 | Temporary files filled disk in align_reads |
| Docker pull failures | 2 | Rate-limited pulling image from Docker Hub |
| Input data errors | 1 | Malformed BAM file (sample_47) |

Recommendations:
1. Increase memory to 32GB for call_variants task
2. Increase disk size to 200GB for align_reads
3. Consider using a private container registry to avoid Docker Hub rate limits
4. Check sample_47 BAM file integrity before resubmitting
```

```
Human: I ran our new optimized code as submission abc-123-new and the baseline as xyz-789-old
on the same 200 samples. Can you verify the outputs match and check if runtime improved?

Claude: I'll compare both submissions for correctness and performance.
[Claude calls get_submission_status for both submissions]
[Claude calls get_job_metadata for sample of workflows from each]
[Claude calls get_workflow_outputs to compare output files]
[Claude calls get_workflow_cost for both]

**Regression Test Results: New Code vs Baseline**

Correctness (200 samples):
- Output files match: 198/200 samples (99%)
- Minor differences: 2 samples have VCF annotation order differences (functionally equivalent)
- No data quality regressions detected

Performance (call_variants step):
- Baseline avg runtime: 47 minutes
- New code avg runtime: 31 minutes
- Improvement: 34% faster

Cost:
- Baseline total: $156.40
- New code total: $118.20
- Savings: 24% reduction

Conclusion: The optimization is successful. Outputs are equivalent and the
call_variants step shows the expected ~35% runtime improvement. Safe to merge.

Human: this is great, please post your findings as a comment on the open PR on this git branch.
```

## Data Privacy and Security Considerations

⚠️ **This MCP server provides Claude with the ability to read data from your Terra workspaces. Exercise extreme caution when working with sensitive, restricted, or regulated data.**

### ❌ Do NOT Use This Tool To:

1. **Extract Legally Restricted Genomic Data**
   - Do NOT retrieve actual genome sequences, genotypes, or other individual-level genetic data
   - Do NOT ask Claude to analyze raw genomic data files (FASTQ, BAM, VCF, etc.)
   - Do NOT copy restricted research data from controlled-access databases

2. **Share Protected Health Information (PHI) with Free-Tier LLMs**
   - Free and consumer LLM services (including Claude.ai free tier) may use your conversations for training
   - Do NOT share patient identifiers, clinical data, or other PHI without proper data use agreements
   - Always verify your LLM service's data retention and usage policies before working with sensitive data

3. **Violate Data Use Agreements or IRB Protocols**
   - Terra workspaces often contain data with strict usage restrictions
   - Do NOT use this tool in ways that violate your institution's IRB protocols or data use agreements
   - Do NOT share controlled-access data beyond approved research teams

### ✅ Safe Use Cases:

- **Metadata Analysis**: Query workspace organization, workflow configurations, submission statuses
- **Log Debugging**: Analyze error messages and execution logs (which typically don't contain sensitive data)
- **Workflow Optimization**: Review pipeline configurations, resource usage, and cost information
- **De-identified Data**: Work with properly de-identified or synthetic datasets that comply with all applicable regulations
- **Secure Compute Environments**: Use with restricted data when operating within a NIST-800-171 compliant compute boundary (e.g., Vertex AI within authorized Google Cloud projects with proper security controls)

### Regulatory References

The NIH and other regulatory bodies have issued guidance on the use of generative AI with genomic and health data:

- **NIH NOT-OD-25-081**: [Expectations for the Use of Generative Artificial Intelligence (GenAI) by Recipients of NIH Funding](https://grants.nih.gov/grants/guide/notice-files/NOT-OD-25-081.html)
- **NIH NOT-OD-24-157**: [Notice of Supplemental Information for NIH-Funded Researchers and Applicant Institutions on Generative Artificial Intelligence (GenAI) Tools](https://grants.nih.gov/grants/guide/notice-files/NOT-OD-24-157.html)
- **Legal Analysis**: [Generative AI and Genomic Privacy](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5683067) - Academic analysis of privacy risks

**When in doubt, consult your institution's IRB, data governance office, or legal counsel before using this tool with potentially sensitive data.**

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
# Read-only mode (default)
fastmcp dev src/terra_mcp/server.py

# Write-enabled mode
fastmcp dev src/terra_mcp/server.py -- --allow-writes
```

This starts an interactive development session where you can test tools.

### Running the Server (Production)

Run the server with stdio transport (for Claude Desktop integration):

```bash
# Read-only mode (default - recommended for safety)
fastmcp run src/terra_mcp/server.py

# Write-enabled mode (for active development)
fastmcp run src/terra_mcp/server.py -- --allow-writes
```

Or run directly:

```bash
# Read-only mode (default)
python src/terra_mcp/server.py

# Write-enabled mode
python src/terra_mcp/server.py --allow-writes
```

### Claude Desktop Integration

To use this MCP server with Claude Desktop, add the following to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

#### Read-Only Mode (Default - Recommended for Safety)

This configuration enables all read-only tools (monitoring, querying, viewing) but blocks write operations:

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

#### Write-Enabled Mode (For Active Development)

To enable write operations (`update_method_config`, `copy_method_config`, `submit_workflow`, `abort_submission`, `upload_entities`), add the `--allow-writes` flag:

```json
{
  "mcpServers": {
    "terra": {
      "command": "python3",
      "args": [
        "/absolute/path/to/fiss-mcp/src/terra_mcp/server.py",
        "--allow-writes"
      ]
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
      "args": [
        "/absolute/path/to/fiss-mcp/src/terra_mcp/server.py",
        "--allow-writes"
      ],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/your/credentials.json"
      }
    }
  }
}
```

After updating the configuration, restart Claude Desktop.

### Claude Code Integration

#### Read-Only Mode (Default - Recommended for Safety)

To use this MCP server with Claude Code in read-only mode (monitoring, querying, viewing only), run:

```bash
claude mcp add terra --transport stdio \
  -- python3 \
  /absolute/path/to/fiss-mcp/src/terra_mcp/server.py
```

#### Write-Enabled Mode (For Active Development)

To enable write operations (`update_method_config`, `copy_method_config`, `submit_workflow`, `abort_submission`, `upload_entities`), add the `--allow-writes` flag:

```bash
claude mcp add terra --transport stdio \
  -- python3 \
  /absolute/path/to/fiss-mcp/src/terra_mcp/server.py \
  --allow-writes
```

Replace `/absolute/path/to/fiss-mcp` with the actual path to your cloned repository.

**Note**: If you installed dependencies in a Python virtual environment, use the absolute path to your venv's Python interpreter instead of `python3`:

```bash
# Read-only mode
claude mcp add terra --transport stdio \
  -- /absolute/path/to/venv/bin/python3 \
  /absolute/path/to/fiss-mcp/src/terra_mcp/server.py

# Write-enabled mode
claude mcp add terra --transport stdio \
  -- /absolute/path/to/venv/bin/python3 \
  /absolute/path/to/fiss-mcp/src/terra_mcp/server.py \
  --allow-writes
```

If you need to specify Google Cloud credentials:

```bash
# Read-only mode with credentials
claude mcp add terra --transport stdio \
  --env GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/credentials.json \
  -- python3 \
  /absolute/path/to/fiss-mcp/src/terra_mcp/server.py

# Write-enabled mode with credentials
claude mcp add terra --transport stdio \
  --env GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/credentials.json \
  -- python3 \
  /absolute/path/to/fiss-mcp/src/terra_mcp/server.py \
  --allow-writes
```

To verify the server is connected:
```bash
claude mcp list
```

To reconnect after code changes:
```bash
claude mcp reconnect terra
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

The test suite includes 93 comprehensive tests:
- Server initialization verification
- Tool registration checks (all 16 tools)
- Mocked FISS API responses
- Mocked GCS log fetching and truncation
- Error handling scenarios (404s, 403s, 400s, 409s, API failures, GCS errors)
- Parameter validation (max_workflows, include_keys, fetch_content, truncate, expression, entity_data, etc.)
- Helper function tests (truncation logic, GCS URL parsing)
- Read-only mode safety feature tests (7 tests verifying write operations are properly blocked)
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
6. Add write access check if the tool modifies Terra resources
7. Add tests in `tests/test_server.py` following TDD principles (use `enable_writes` fixture for write tools)

Example (read-only tool):
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

Example (write tool):
```python
@mcp.tool()
async def my_write_tool(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    ctx: Context,
) -> dict[str, Any]:
    """Tool that modifies Terra resources.

    Args:
        workspace_namespace: Description
        workspace_name: Description

    Returns:
        Dictionary with result data
    """
    # Check write access first
    _check_write_access(ctx)

    try:
        ctx.info("Starting write operation")
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

1. **Read-only by default**: Server runs in safe mode; write operations require explicit `--allow-writes` flag
2. **Explicit workspace identification**: Always require namespace + name (no implicit "current workspace")
3. **Actionable error messages**: All errors provide clear next steps for LLMs
4. **Smart log truncation**: For error logs, return tail (last ~25K chars) where failures appear
5. **Two-tier error handling**: ToolError for expected failures, masked exceptions for internal errors

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
