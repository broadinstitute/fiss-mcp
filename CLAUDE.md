# Terra.Bio MCP Server

## Project Purpose
Build an MCP (Model Context Protocol) server that enables Claude and Claude Code to interact with Terra.Bio workspaces via the FISS (firecloud) API. Primary use cases:
- Develop and debug WDL pipelines with Claude Code monitoring Terra workflow runs
- Run regression tests against benchmark datasets on Terra
- Monitor job submissions, interpret logs, and debug failures

## Technical Approach
- **Framework**: Python with [FastMCP](https://github.com/jlowin/fastmcp) (mcp Python SDK)
- **API Client**: [firecloud/FISS](https://github.com/broadinstitute/fiss) Python library
- **Authentication**: Local user has pre-authenticated Google credentials that work with FISS
- **Development Guide**: Follow [MCP Specification](https://modelcontextprotocol.io/llms-full.txt) and [FastMCP docs](https://github.com/jlowin/fastmcp)

## Key Design Decisions

### Workspace Identification
- Always require explicit workspace namespace + name in tool calls
- No implicit "current workspace" to avoid confusion
- Format: `workspace_namespace="my-namespace"`, `workspace_name="my-workspace"`

### Error Handling
- All error messages must be actionable and LLM-friendly
- **WDL logs truncation strategy**:
  - For error logs: Keep the LAST ~25K characters (tail), not first
  - Rationale: Stack traces and actual failures appear at the end
  - Consider smart truncation: first 5K chars + last 20K chars for context
  - Always indicate when truncation occurred and total log size
- Provide clear next steps in error responses

### Response Formats
- Support both JSON and Markdown response formats where appropriate
- Default to concise responses, offer detailed option
- Always include human-readable summaries with technical data

## Implementation Summary

All planned tools have been successfully implemented following test-driven development (TDD) principles.

### Workspace & Data Discovery (3 tools)
1. ✅ `list_workspaces` - List user's accessible Terra workspaces
2. ✅ `get_workspace_data_tables` - List data tables in a workspace
3. ✅ `get_entities` - Read entity data from Terra data tables
   - Returns all entities of specified type with attributes

### Workflow Monitoring & Status (6 tools)
4. ✅ `list_submissions` - List all submissions in a workspace
   - Returns full submission metadata including status, submitter, workflows
5. ✅ `get_submission_status` - Check workflow submission status by ID
   - Supports `max_workflows` parameter (default: 10, use 0 for all)
6. ✅ `get_job_metadata` - Get Cromwell metadata for specific workflows
   - By default excludes verbose fields to reduce response size: `commandLine`, `submittedFiles`, `callCaching`, `executionEvents`, `workflowProcessingEvents`, `backendLabels`, `labels`
   - Supports `include_keys` and `exclude_keys` for filtering response
   - Pass `exclude_keys=[]` to get full metadata including normally excluded fields
7. ✅ `get_workflow_logs` - Fetch stderr/stdout from GCS
   - Returns GCS URLs by default (fast)
   - `fetch_content=True` to fetch actual log content from GCS
   - Smart truncation (first 5K + last 20K chars) by default when fetching
   - `truncate=False` for full logs when needed
   - `max_chars` parameter to customize truncation limit
8. ✅ `get_workflow_outputs` - Get output files from completed workflows
   - Returns workflow outputs dictionary (GCS paths and scalar values)
9. ✅ `get_workflow_cost` - Get cost information for workflows
   - Returns cost breakdown by compute, storage, network
   - Note: Cost data may be delayed (takes hours for GCP to process)

### Workflow Configuration & Management (5 tools)
10. ✅ `get_method_config` - Get method configuration details
    - Returns WDL workflow definition and configuration
    - Useful for verifying workflow versions match Git commits
11. ✅ `update_method_config` - Update/modify method configuration
    - Change workflow versions, inputs, outputs
    - Essential for switching between Git branches during development
12. ✅ `copy_method_config` - Duplicate method configuration to new name
    - Copy workflow configurations within workspace
    - Useful for creating test variants of workflows
13. ✅ `submit_workflow` - Launch a WDL workflow
    - Submit workflows with specified method configuration
    - Supports both single entity and batch processing via expressions
    - Configurable call caching
14. ✅ `abort_submission` - Cancel a running workflow
    - Cancels all workflows in a submission

### Data Management (1 tool)
15. ✅ `upload_entities` - Upload or update entity data in Terra data tables
    - Validates entity format (name, entityType, attributes)
    - Supports batch uploads of multiple entities
    - Comprehensive error handling for invalid data

## FISS/Terra Context

### Key Terra Concepts
- **Workspace**: Container for data, workflows, and analyses (identified by namespace + name)
- **Data Tables**: Structured data (entities) used as workflow inputs
- **Method Configuration**: Workflow configuration that links a WDL method to specific inputs/outputs
  - Contains method snapshot ID (version), input/output mappings, and root entity type
  - Identified by configuration namespace + configuration name
  - Can be updated to point to different WDL versions (essential for development workflows)
- **Submission**: A workflow run, can contain multiple workflows
- **Workflow**: Individual WDL execution within a submission
- **Job**: Individual task execution within a workflow

### Important FISS API Notes
- API has rate limits - implement exponential backoff
- Workflow logs are in Google Cloud Storage (GCS), accessed via gs:// URLs
- Logs are duplicated in both GCS and GCP Batch Logs Explorer
- Submission status values: "Submitted", "Running", "Succeeded", "Failed", "Aborted"
- Job metadata includes Cromwell metadata with detailed execution info
- `fapi.get_workflow_metadata()` supports `include_key` and `exclude_key` parameters for filtering

### FISS API Functions Used

**Workspace & Discovery:**
- `fapi.list_workspaces()` - List accessible workspaces
- `fapi.list_entity_types(namespace, workspace)` - List data tables
- `fapi.get_entities(namespace, workspace, etype)` - Get all entities of a type

**Workflow Monitoring:**
- `fapi.list_submissions(namespace, workspace)` - List all submissions
- `fapi.get_submission(namespace, workspace, submission_id)` - Get submission status
- `fapi.get_workflow_metadata(namespace, workspace, submission_id, workflow_id, include_key, exclude_key)` - Get Cromwell metadata
- `fapi.get_workflow_outputs(namespace, workspace, submission_id, workflow_id)` - Get workflow outputs
- `fapi.get_workflow_cost(namespace, workspace, submission_id, workflow_id)` - Get cost information

**Workflow Management:**
- `fapi.get_workspace_config(namespace, workspace, cnamespace, config)` - Get method config details
- `fapi.update_workspace_config(namespace, workspace, cnamespace, configname, body)` - Update method config
- `fapi.copy_config_from_repo(namespace, workspace, from_cnamespace, from_config, to_cnamespace, to_config)` - Copy method config
- `fapi.create_submission(namespace, workspace, cnamespace, config, entity_type, entity_name, expression, use_callcache)` - Submit workflow
- `fapi.abort_submission(namespace, workspace, submission_id)` - Cancel submission

**Data Management:**
- `fapi.upload_entities(namespace, workspace, entity_data)` - Upload/update entities

## Development Notes & Learnings

### Test-Driven Development (TDD)
- All tools were implemented following TDD principles: write tests first, then implement
- 53 total tests with 75% code coverage
- Comprehensive test coverage includes:
  - Success scenarios for all tools
  - Error handling (404, 403, 400, 409 responses)
  - Edge cases (empty data, invalid formats, truncation)
  - Helper function tests (GCS log fetching, truncation logic)
- Tests use mocked FISS API responses for fast, deterministic execution
- Mock GCS client for log fetching tests to avoid external dependencies

### Testing with FastMCP
- FastMCP uses decorators that wrap functions in `FunctionTool` objects
- Access underlying function via `.fn` attribute: `mcp._tool_manager._tools["tool_name"].fn`
- Always import `ToolError` from `fastmcp.exceptions`, not `fastmcp` directly
- Use `pytest.mark.asyncio` for all async tool tests
- Mock context object (`ctx = MagicMock()`) for logging verification

### FISS Installation Quirks
- Firecloud requires `setuptools<80` due to deprecated `package_index` (see [fiss#192](https://github.com/broadinstitute/fiss/issues/192))
- Must use `pip install --no-build-isolation` to use local setuptools
- Document this in requirements.txt and installation instructions
- GitHub Actions workflow configured with proper dependency installation order

### GCS Log Fetching
- Use `google-cloud-storage` library to fetch log content
- Parse gs:// URLs: `gs://bucket/path/to/file` → bucket="bucket", blob="path/to/file"
- Logs can be large (>1MB), always provide truncation options
- Smart truncation preserves context (first 5K) and errors (last 20K)
- Return both URLs and optional content for flexibility
- Handle GCS fetch failures gracefully (return None, log error)

### MCP Server Design Patterns
- Long-running workflows: Claude will need to poll status, MCP is stateless
- Always provide sensible defaults but allow full data access when needed
- Use `Annotated` type hints for parameter descriptions (visible to LLMs)
- Two-tier error handling: `ToolError` for user-facing, masked exceptions for internal
- Comprehensive error messages with actionable next steps
- Validation before API calls to catch errors early
- Consistent response formats across all tools
- **Context size optimization**: Default to minimal responses to avoid exhausting LLM context
  - `get_job_metadata` excludes 7 verbose fields by default: `commandLine`, `submittedFiles`, `callCaching`, `executionEvents`, `workflowProcessingEvents`, `backendLabels`, `labels`
  - Users can override with explicit parameters to get full data when needed (pass `exclude_keys=[]`)

### Code Quality & CI/CD
- Ruff for linting and formatting (enforced in CI)
- GitHub Actions workflow with test matrix (Python 3.10, 3.11, 3.12)
- Codecov integration for coverage tracking
- Formatting check prevents commits with style violations

## Future Enhancements

Potential areas for expansion beyond the current 15 tools:

### Workflow Analysis & Optimization
- Automatic cost optimization suggestions based on resource usage
- Call-caching analysis and recommendations
- Workflow performance profiling and bottleneck identification
- Historical trend analysis for workflow execution times and costs

### Enhanced Error Handling & Reliability
- Automatic retry logic for transient API failures
- Exponential backoff for rate limit handling
- Batch operation support with progress tracking
- Detailed validation of WDL inputs before submission

### WDL Integration
- WDL parsing and syntax validation
- Integration with WDL linting tools (womtool, miniwdl)
- WDL dependency analysis and visualization
- Automatic WDL variable extraction for input mapping

### Advanced Data Operations
- Bulk entity operations with transaction support
- Workspace cloning and migration tools
- Entity query language with complex filters
- Pagination support for large entity tables
- TSV import/export for entity data

### Terra Platform Integration
- Terra notebook operations and management
- Workspace data model visualization
- Bucket management and access control
- Billing project administration

### Developer Experience
- Interactive workflow debugging with breakpoints
- Workflow execution replay and what-if analysis
- Integration with IDE extensions (VS Code, PyCharm)
- Workflow template library and scaffolding
