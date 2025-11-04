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

### Phase 1: Read-Only Tools (Priority)
1. `list_workspaces` - List user's accessible Terra workspaces
2. `get_workspace_data_tables` - List data tables in a workspace
3. `get_submission_status` - Check workflow submission status by ID
4. `get_job_metadata` - Get details about a specific job
5. `get_submission_logs` - Fetch stderr/stdout from jobs
   - Tail logs (last ~25K chars) by default for errors
   - Offer option to fetch from beginning if needed
   - Always show total log size and truncation applied

### Phase 2: Monitoring Tools
6. `list_submissions` - List submissions with filtering by status/date
7. `get_workflow_outputs` - Get output files from completed workflows
8. `get_workflow_cost` - Get cost information if available

### Phase 3: Write Operations (After read-only tools validated)
9. `upload_data_to_table` - Add/update rows in Terra data tables
10. `submit_workflow` - Launch a WDL workflow
11. `abort_submission` - Cancel a running workflow

## FISS/Terra Context

### Key Terra Concepts
- **Workspace**: Container for data, workflows, and analyses (identified by namespace + name)
- **Data Tables**: Structured data (entities) used as workflow inputs
- **Submission**: A workflow run, can contain multiple workflows
- **Workflow**: Individual WDL execution within a submission
- **Job**: Individual task execution within a workflow

### Important FISS API Notes
- API has rate limits - implement exponential backoff
- Workflow logs are in Google Cloud Storage, accessed via signed URLs
- Submission status values: "Submitted", "Running", "Succeeded", "Failed", "Aborted"
- Job metadata includes Cromwell metadata with detailed execution info

## Development Notes
- Test FISS connectivity early: `from firecloud import api as fapi`
- Use MCP evaluation harness for testing tools in isolation
- Long-running workflows: Claude will need to poll status, MCP is stateless
- Consider adding tool to parse/summarize Terra's call-caching information

## Future Enhancements (Post-MVP)
- Workflow cost analysis and optimization suggestions
- Automatic retry logic for failed jobs
- Integration with WDL linting/validation
- Support for Terra notebook operations
