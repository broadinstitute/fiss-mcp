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

## Implementation Phases

### Phase 1: Read-Only Tools ✅ COMPLETED
1. ✅ `list_workspaces` - List user's accessible Terra workspaces
2. ✅ `get_workspace_data_tables` - List data tables in a workspace
3. ✅ `get_submission_status` - Check workflow submission status by ID
   - Supports `max_workflows` parameter (default: 10, use 0 for all)
4. ✅ `get_job_metadata` - Get Cromwell metadata for specific workflows
   - Supports `include_keys` and `exclude_keys` for filtering response
5. ✅ `get_workflow_logs` - Fetch stderr/stdout from GCS
   - Returns GCS URLs by default (fast)
   - `fetch_content=True` to fetch actual log content from GCS
   - Smart truncation (first 5K + last 20K chars) by default when fetching
   - `truncate=False` for full logs when needed
   - `max_chars` parameter to customize truncation limit

### Phase 2: Monitoring Tools ✅ COMPLETED
6. ✅ `list_submissions` - List all submissions in a workspace
   - Returns full submission metadata including status, submitter, workflows
7. ✅ `get_workflow_outputs` - Get output files from completed workflows
   - Returns workflow outputs dictionary (GCS paths and scalar values)
8. ✅ `get_workflow_cost` - Get cost information for workflows
   - Returns cost breakdown by compute, storage, network
   - Note: Cost data may be delayed (takes hours for GCP to process)

### Phase 3: Workflow Management Tools
9. `get_entities` - Read data from Terra data tables/entities
   - Support filtering, pagination, and attribute selection
   - Return entity metadata and attributes as structured data
10. `get_method_config` - Get method configuration details
   - Return WDL workflow definition and configuration
   - Useful for verifying workflow versions match Git commits
11. `update_method_config` - Update/modify method configuration
   - Change workflow versions, inputs, outputs
   - Essential for switching between Git branches during development
12. `copy_method_config` - Duplicate method configuration to new name
   - Copy workflow configurations within workspace
   - Useful for creating test variants of workflows
13. `submit_workflow` - Launch a WDL workflow
   - Submit workflows with specified method configuration
   - Support selecting different workflow versions
14. `abort_submission` - Cancel a running workflow

### Phase 4: Data Management Tools
15. `upload_data_to_table` - Add/update rows in Terra data tables
   - Upload entity data for workflow inputs

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

### Phase 3 API Functions
**Entity/Table Data:**
- `fapi.get_entities(namespace, workspace, etype)` - Get all entities of a type
- `fapi.get_entities_tsv(namespace, workspace, etype, attrs=None)` - Get entities as TSV
- `fapi.get_entity(namespace, workspace, etype, ename)` - Get single entity
- `fapi.get_entities_query(...)` - Paginated query with filtering

**Method Configurations:**
- `fapi.get_workspace_config(namespace, workspace, cnamespace, config)` - Get method config details
- `fapi.get_repository_method(namespace, method, snapshot_id)` - Get WDL from methods repo
- `fapi.update_workspace_config(namespace, workspace, cnamespace, configname, body)` - Update method config
- `fapi.copy_config_from_repo(...)` - Copy method config from repo to workspace
- `fapi.validate_config(namespace, workspace, cnamespace, config)` - Validate method config

**Workflow Submission:**
- `fapi.create_submission(...)` - Submit workflow (already documented in Phase 1)
- `fapi.abort_submission(namespace, workspace, submission_id)` - Cancel submission

## Development Notes & Learnings

### Testing with FastMCP
- FastMCP uses decorators that wrap functions in `FunctionTool` objects
- Access underlying function via `.fn` attribute: `mcp._tool_manager._tools["tool_name"].fn`
- Always import `ToolError` from `fastmcp.exceptions`, not `fastmcp` directly
- Test FISS connectivity early: `from firecloud import api as fapi`

### FISS Installation Quirks
- Firecloud requires `setuptools<80` due to deprecated `package_index` (see [fiss#192](https://github.com/broadinstitute/fiss/issues/192))
- Must use `pip install --no-build-isolation` to use local setuptools
- Document this in requirements.txt and installation instructions

### GCS Log Fetching
- Use `google-cloud-storage` library to fetch log content
- Parse gs:// URLs: `gs://bucket/path/to/file` → bucket="bucket", blob="path/to/file"
- Logs can be large (>1MB), always provide truncation options
- Smart truncation preserves context (first 5K) and errors (last 20K)
- Return both URLs and optional content for flexibility

### MCP Server Design Patterns
- Long-running workflows: Claude will need to poll status, MCP is stateless
- Always provide sensible defaults but allow full data access when needed
- Use `Annotated` type hints for parameter descriptions (visible to LLMs)
- Two-tier error handling: `ToolError` for user-facing, masked exceptions for internal
- Consider adding tool to parse/summarize Terra's call-caching information

## Future Enhancements (Post-MVP)
- Workflow cost analysis and optimization suggestions
- Automatic retry logic for failed jobs
- Integration with WDL linting/validation
- Support for Terra notebook operations
