"""Terra.Bio MCP Server

MCP server for interacting with Terra.Bio workspaces via the FISS API.
Provides tools for listing workspaces, querying data tables, and monitoring workflow submissions.
"""

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from firecloud import api as fapi
from google.cloud import storage

# Initialize MCP server
mcp = FastMCP(
    "Terra.Bio MCP Server",
    instructions=(
        "Interact with Terra.Bio workspaces and workflows via FISS API. "
        "Monitor WDL pipeline runs, query data tables, and check submission status."
    ),
    mask_error_details=True,  # Hide internal errors in production
)


# ===== Helper Functions =====


def _truncate_log_content(content: str, max_chars: int = 25000) -> tuple[str, bool]:
    """Apply smart truncation to log content.

    Keeps the first ~5K characters and last ~20K characters for context.
    This ensures error messages (which appear at the end) are preserved while
    providing some initial context.

    Args:
        content: The log content to truncate
        max_chars: Maximum total characters to return (default: 25000)

    Returns:
        Tuple of (truncated_content, was_truncated)
    """
    if len(content) <= max_chars:
        return content, False

    # Smart truncation: first 5K + last 20K chars
    head_chars = min(5000, max_chars // 5)
    tail_chars = max_chars - head_chars - 100  # Reserve 100 chars for truncation message

    head = content[:head_chars]
    tail = content[-tail_chars:]

    truncation_msg = (
        f"\n\n... [Truncated {len(content) - max_chars:,} characters. "
        f"Total log size: {len(content):,} characters] ...\n\n"
    )

    return head + truncation_msg + tail, True


def _fetch_gcs_log(gcs_url: str, ctx: Context) -> str | None:
    """Fetch log content from Google Cloud Storage.

    Args:
        gcs_url: GCS URL in format gs://bucket/path/to/file
        ctx: FastMCP context for logging

    Returns:
        Log content as string, or None if fetch fails
    """
    if not gcs_url or not gcs_url.startswith("gs://"):
        return None

    try:
        # Parse GCS URL: gs://bucket/path/to/file
        url_parts = gcs_url[5:].split("/", 1)
        if len(url_parts) != 2:
            ctx.error(f"Invalid GCS URL format: {gcs_url}")
            return None

        bucket_name, blob_name = url_parts

        # Initialize GCS client and fetch blob
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # Download as text
        content = blob.download_as_text()
        ctx.info(f"Successfully fetched log from {gcs_url} ({len(content)} chars)")
        return content

    except Exception as e:
        ctx.error(f"Failed to fetch log from {gcs_url}: {type(e).__name__}: {e}")
        return None


# ===== Phase 1: Read-Only Tools =====


@mcp.tool()
async def list_workspaces(ctx: Context) -> list[dict[str, Any]]:
    """List all Terra workspaces accessible to the authenticated user.

    Returns workspace information including namespace, name, creator, and creation date.
    This tool requires valid Google credentials configured for FISS API access.

    Returns:
        List of workspace dictionaries with keys: namespace, name, created_by, created_date
    """
    try:
        ctx.info("Fetching accessible Terra workspaces")
        response = fapi.list_workspaces()

        if response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch workspaces (HTTP {response.status_code}). "
                "Please check your Google credentials and Terra access permissions."
            )

        workspaces = response.json()
        ctx.info(f"Successfully retrieved {len(workspaces)} accessible workspaces")

        # Extract relevant workspace information
        result = [
            {
                "namespace": ws["workspace"]["namespace"],
                "name": ws["workspace"]["name"],
                "created_by": ws["workspace"]["createdBy"],
                "created_date": ws["workspace"]["createdDate"],
            }
            for ws in workspaces
        ]

        return result

    except ToolError:
        # Re-raise ToolErrors as-is
        raise
    except Exception as e:
        ctx.error(f"Unexpected error listing workspaces: {type(e).__name__}: {e}")
        raise ToolError(
            "Failed to list workspaces. Please verify your Google credentials are configured "
            "correctly and you have access to Terra.Bio."
        )


@mcp.tool()
async def get_workspace_data_tables(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    ctx: Context,
) -> dict[str, Any]:
    """List all data tables in a Terra workspace.

    Data tables (also called entity types) store structured data used as workflow inputs.
    Returns table names and row counts for each table in the workspace.

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace

    Returns:
        Dictionary containing:
        - workspace: Full workspace identifier (namespace/name)
        - tables: List of tables with name and count fields
    """
    try:
        ctx.info(f"Fetching data tables for workspace {workspace_namespace}/{workspace_name}")

        response = fapi.list_entity_types(workspace_namespace, workspace_name)

        if response.status_code == 404:
            raise ToolError(
                f"Workspace '{workspace_namespace}/{workspace_name}' not found. "
                "Please verify the workspace namespace and name are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this workspace."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch data tables (HTTP {response.status_code}). "
                "Please check the workspace exists and you have access."
            )

        entity_types = response.json()
        ctx.info(f"Successfully retrieved {len(entity_types)} data tables")

        return {
            "workspace": f"{workspace_namespace}/{workspace_name}",
            "tables": [
                {
                    "name": entity["name"],
                    "count": entity["count"],
                }
                for entity in entity_types
            ],
        }

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching data tables: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch data tables for workspace {workspace_namespace}/{workspace_name}"
        )


@mcp.tool()
async def get_submission_status(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    submission_id: Annotated[str, "Unique submission identifier (UUID)"],
    ctx: Context,
    max_workflows: Annotated[
        int | None,
        "Maximum number of workflows to return (default: 10, use 0 or None for all workflows)",
    ] = 10,
) -> dict[str, Any]:
    """Get the current status of a workflow submission.

    A submission represents a workflow run in Terra, which can contain multiple workflows.
    Returns detailed status information including overall submission status, workflow counts,
    and a summary of workflow states (Succeeded, Failed, Running, etc.).

    By default, returns the first 10 workflows for readability. Use max_workflows=0 or
    max_workflows=None to retrieve all workflows if needed for detailed analysis.

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        submission_id: The unique identifier (UUID) of the submission
        max_workflows: Maximum workflows to return (default: 10, use 0/None for all)

    Returns:
        Dictionary containing:
        - submission_id: The submission UUID
        - status: Overall submission status (Submitted, Running, Succeeded, Failed, Aborted)
        - submission_date: When the submission was created
        - workflow_count: Total number of workflows in this submission
        - status_summary: Count of workflows by status
        - workflows: List of workflows with details (limited by max_workflows)
        - note: Indication if workflow list was truncated
    """
    try:
        ctx.info(f"Fetching status for submission {submission_id}")

        response = fapi.get_submission(
            workspace_namespace,
            workspace_name,
            submission_id,
        )

        if response.status_code == 404:
            raise ToolError(
                f"Submission '{submission_id}' not found in workspace "
                f"'{workspace_namespace}/{workspace_name}'. "
                "Please verify the submission ID and workspace are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this submission."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch submission status (HTTP {response.status_code}). "
                "Please check the workspace and submission ID."
            )

        submission = response.json()

        # Calculate workflow status summary
        workflows = submission.get("workflows", [])
        status_counts: dict[str, int] = {}
        for workflow in workflows:
            status = workflow.get("status", "Unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        ctx.info(
            f"Retrieved submission with {len(workflows)} workflows, "
            f"status: {submission.get('status')}"
        )

        # Determine workflow limit (0 or None means return all)
        if max_workflows is None or max_workflows <= 0:
            limited_workflows = workflows
            note = None
        else:
            limited_workflows = workflows[:max_workflows]
            note = (
                f"Showing first {max_workflows} of {len(workflows)} workflows"
                if len(workflows) > max_workflows
                else None
            )

        return {
            "submission_id": submission_id,
            "status": submission.get("status"),
            "submission_date": submission.get("submissionDate"),
            "workflow_count": len(workflows),
            "status_summary": status_counts,
            "workflows": limited_workflows,
            "note": note,
        }

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching submission status: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch status for submission {submission_id} in workspace "
            f"{workspace_namespace}/{workspace_name}"
        )


@mcp.tool()
async def get_job_metadata(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    submission_id: Annotated[str, "Submission identifier (UUID)"],
    workflow_id: Annotated[str, "Workflow identifier (UUID)"],
    ctx: Context,
    include_keys: Annotated[
        list[str] | None,
        "Optional list of metadata keys to include (returns only these keys, overrides exclude_keys)",
    ] = None,
    exclude_keys: Annotated[
        list[str] | None,
        "Optional list of metadata keys to exclude (default excludes verbose fields to reduce size)",
    ] = None,
) -> dict[str, Any]:
    """Get detailed Cromwell metadata for a specific workflow/job.

    Returns comprehensive execution metadata including task-level details, execution status,
    timing information, and references to log files. This is the Cromwell metadata JSON.

    By default, excludes verbose fields to reduce response size: 'commandLine', 'submittedFiles',
    'callCaching', 'executionEvents', 'workflowProcessingEvents', 'backendLabels', 'labels'.
    To include everything, pass exclude_keys=[] explicitly.

    Use include_keys or exclude_keys to filter the response for specific information:
    - include_keys=['status', 'failures'] - Get only status and failure information
    - exclude_keys=['calls'] - Omit detailed call information to reduce response size
    - exclude_keys=[] - Include all fields (including commandLine and submittedFiles)

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        submission_id: The submission UUID containing this workflow
        workflow_id: The workflow UUID to get metadata for
        include_keys: Optional list of metadata keys to include (overrides default exclusions)
        exclude_keys: Optional list of metadata keys to exclude (default: excludes 7 verbose fields)

    Returns:
        Dictionary containing Cromwell workflow metadata (structure depends on filtering)
    """
    try:
        ctx.info(f"Fetching metadata for workflow {workflow_id} in submission {submission_id}")

        # Apply default exclusions if no explicit filtering specified
        # This reduces response size significantly by excluding verbose fields
        if include_keys is None and exclude_keys is None:
            exclude_keys = [
                "commandLine",
                "submittedFiles",
                "callCaching",
                "executionEvents",
                "workflowProcessingEvents",
                "backendLabels",
                "labels",
            ]
            ctx.info(
                "Applying default exclusions: commandLine, submittedFiles, callCaching, "
                "executionEvents, workflowProcessingEvents, backendLabels, labels"
            )

        response = fapi.get_workflow_metadata(
            workspace_namespace,
            workspace_name,
            submission_id,
            workflow_id,
            include_key=include_keys,
            exclude_key=exclude_keys,
        )

        if response.status_code == 404:
            raise ToolError(
                f"Workflow '{workflow_id}' not found in submission '{submission_id}' "
                f"for workspace '{workspace_namespace}/{workspace_name}'. "
                "Please verify the workflow ID and submission ID are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this workflow."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch workflow metadata (HTTP {response.status_code}). "
                "Please check the workspace and workflow IDs."
            )

        metadata = response.json()
        ctx.info(f"Successfully retrieved metadata for workflow {workflow_id}")

        return metadata

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching workflow metadata: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch metadata for workflow {workflow_id} in submission {submission_id}"
        )


@mcp.tool()
async def get_workflow_logs(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    submission_id: Annotated[str, "Submission identifier (UUID)"],
    workflow_id: Annotated[str, "Workflow identifier (UUID)"],
    ctx: Context,
    fetch_content: Annotated[
        bool,
        "Whether to fetch actual log content from GCS (default: False, returns URLs only)",
    ] = False,
    truncate: Annotated[
        bool,
        "Whether to truncate log content (default: True when fetch_content=True)",
    ] = True,
    max_chars: Annotated[
        int,
        "Maximum characters per log file when truncating (default: 25000)",
    ] = 25000,
) -> dict[str, Any]:
    """Get workflow execution logs and task status.

    By default, returns stderr and stdout log file locations (Google Cloud Storage URLs)
    from the workflow metadata for each task execution.

    With fetch_content=True, fetches the actual log content from GCS. Logs are truncated
    by default using a smart strategy (first 5K + last 20K chars) to keep error messages
    while providing context. Set truncate=False to get full logs.

    This tool is useful for:
    - Debugging workflow failures (fetch stderr with truncation)
    - Getting GCS paths to log files for external analysis
    - Seeing execution status and retry attempts for each task

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        submission_id: The submission UUID containing this workflow
        workflow_id: The workflow UUID to get logs for
        fetch_content: Whether to fetch actual log content from GCS
        truncate: Whether to apply smart truncation to logs (ignored if fetch_content=False)
        max_chars: Maximum characters per log when truncating

    Returns:
        Dictionary containing:
        - workflow_id: The workflow UUID
        - workflow_name: Name of the workflow
        - status: Workflow execution status
        - logs: Dictionary mapping task names to their log info (URLs and optionally content)
        - fetch_content: Whether content was fetched (for clarity)
    """
    try:
        ctx.info(f"Fetching log locations for workflow {workflow_id}")

        # Get workflow metadata with only the keys we need for logs
        response = fapi.get_workflow_metadata(
            workspace_namespace,
            workspace_name,
            submission_id,
            workflow_id,
            include_key=["calls", "status", "workflowName"],
        )

        if response.status_code == 404:
            raise ToolError(
                f"Workflow '{workflow_id}' not found in submission '{submission_id}' "
                f"for workspace '{workspace_namespace}/{workspace_name}'. "
                "Please verify the workflow ID and submission ID are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this workflow."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch workflow logs (HTTP {response.status_code}). "
                "Please check the workspace and workflow IDs."
            )

        metadata = response.json()
        calls = metadata.get("calls", {})

        # Extract log URLs and execution info from each task/call
        logs_by_task: dict[str, Any] = {}

        for task_name, task_executions in calls.items():
            for i, execution in enumerate(task_executions):
                # Get stderr and stdout URLs
                stderr_url = execution.get("stderr", "")
                stdout_url = execution.get("stdout", "")

                # Create unique task key for multiple attempts
                task_key = f"{task_name}[{i}]" if len(task_executions) > 1 else task_name

                log_entry: dict[str, Any] = {
                    "stderr_url": stderr_url,
                    "stdout_url": stdout_url,
                    "status": execution.get("executionStatus", "Unknown"),
                    "attempt": execution.get("attempt", 1),
                    "shard": execution.get("shardIndex", -1),
                }

                # Fetch actual log content if requested
                if fetch_content:
                    ctx.info(f"Fetching log content for task {task_key}")

                    # Fetch stderr
                    if stderr_url:
                        stderr_content = _fetch_gcs_log(stderr_url, ctx)
                        if stderr_content is not None:
                            if truncate:
                                stderr_content, was_truncated = _truncate_log_content(
                                    stderr_content, max_chars
                                )
                                log_entry["stderr_truncated"] = was_truncated
                            log_entry["stderr"] = stderr_content

                    # Fetch stdout
                    if stdout_url:
                        stdout_content = _fetch_gcs_log(stdout_url, ctx)
                        if stdout_content is not None:
                            if truncate:
                                stdout_content, was_truncated = _truncate_log_content(
                                    stdout_content, max_chars
                                )
                                log_entry["stdout_truncated"] = was_truncated
                            log_entry["stdout"] = stdout_content

                logs_by_task[task_key] = log_entry

        ctx.info(f"Successfully retrieved log information for {len(logs_by_task)} tasks")

        return {
            "workflow_id": workflow_id,
            "workflow_name": metadata.get("workflowName", ""),
            "status": metadata.get("status", "Unknown"),
            "task_count": len(logs_by_task),
            "logs": logs_by_task,
            "fetch_content": fetch_content,
        }

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching workflow logs: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch logs for workflow {workflow_id} in submission {submission_id}"
        )


# ===== Phase 2: Monitoring Tools =====


@mcp.tool()
async def list_submissions(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    ctx: Context,
    limit: Annotated[
        int | None,
        "Maximum number of submissions to return (default: 20, use None for all submissions)",
    ] = 20,
    status: Annotated[
        str | None,
        "Filter by submission status (e.g., 'Succeeded', 'Failed', 'Running', 'Submitted', 'Aborted')",
    ] = None,
    submitter: Annotated[str | None, "Filter by submitter email address"] = None,
    workflow_name: Annotated[str | None, "Filter by workflow/method configuration name"] = None,
) -> list[dict[str, Any]]:
    """List workflow submissions in a Terra workspace with filtering and pagination.

    Returns a list of submissions in the workspace with their status and metadata,
    sorted by submission date (most recent first). By default, returns the most recent
    20 submissions. Use filtering parameters to narrow results by status, submitter,
    or workflow name.

    Each submission represents one or more workflow executions launched together.
    Common workflow to get submission details:
    1. Use list_submissions to find submissions in a workspace
    2. Use get_submission_status to get detailed status for a specific submission
    3. Use get_workflow_logs to debug failed workflows

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        limit: Maximum submissions to return (default: 20, use None for all)
        status: Filter by submission status (Succeeded, Failed, Running, etc.)
        submitter: Filter by submitter email address
        workflow_name: Filter by method configuration name

    Returns:
        List of submission dictionaries containing:
        - submissionId: Unique identifier for the submission
        - status: Current status (Submitted, Running, Succeeded, Failed, Aborted)
        - submissionDate: When the submission was created
        - submitter: Email of the user who submitted
        - methodConfigurationName: Name of the workflow configuration used
        - workflows: Array of workflow details (IDs and statuses)
    """
    try:
        ctx.info(f"Listing submissions for workspace {workspace_namespace}/{workspace_name}")

        response = fapi.list_submissions(workspace_namespace, workspace_name)

        if response.status_code == 404:
            raise ToolError(
                f"Workspace '{workspace_namespace}/{workspace_name}' not found. "
                "Please verify the workspace namespace and name are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this workspace."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to list submissions (HTTP {response.status_code}). "
                "Please check the workspace exists and you have access."
            )

        submissions = response.json()
        ctx.info(f"Retrieved {len(submissions)} total submissions from API")

        # Sort submissions by date descending (most recent first)
        submissions.sort(key=lambda s: s.get("submissionDate", ""), reverse=True)

        # Apply filters
        filtered_submissions = submissions

        if status:
            filtered_submissions = [s for s in filtered_submissions if s.get("status") == status]
            ctx.info(f"Filtered to {len(filtered_submissions)} submissions with status={status}")

        if submitter:
            filtered_submissions = [
                s for s in filtered_submissions if s.get("submitter") == submitter
            ]
            ctx.info(
                f"Filtered to {len(filtered_submissions)} submissions from submitter={submitter}"
            )

        if workflow_name:
            filtered_submissions = [
                s
                for s in filtered_submissions
                if s.get("methodConfigurationName") == workflow_name
            ]
            ctx.info(
                f"Filtered to {len(filtered_submissions)} submissions "
                f"with workflow_name={workflow_name}"
            )

        # Apply pagination
        if limit is not None and limit > 0:
            paginated_submissions = filtered_submissions[:limit]
            ctx.info(
                f"Returning {len(paginated_submissions)} of {len(filtered_submissions)} "
                f"submissions (limit={limit})"
            )
            return paginated_submissions
        else:
            ctx.info(f"Returning all {len(filtered_submissions)} filtered submissions")
            return filtered_submissions

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error listing submissions: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to list submissions for workspace {workspace_namespace}/{workspace_name}"
        )


@mcp.tool()
async def get_workflow_outputs(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    submission_id: Annotated[str, "Submission identifier (UUID)"],
    workflow_id: Annotated[str, "Workflow identifier (UUID)"],
    ctx: Context,
) -> dict[str, Any]:
    """Get the output files and values from a completed workflow.

    Returns the outputs produced by a workflow execution, including file paths (typically
    Google Cloud Storage URLs) and scalar values. This is useful for retrieving results
    after successful workflow completion.

    Common use cases:
    - Retrieve output file locations for downstream analysis
    - Verify workflow produced expected outputs
    - Get workflow result values for validation

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        submission_id: The submission UUID containing this workflow
        workflow_id: The workflow UUID to get outputs for

    Returns:
        Dictionary containing workflow outputs. Structure depends on the WDL workflow
        definition but typically includes:
        - outputs: Dictionary mapping output variable names to their values/paths
        - id: Workflow identifier
        - tasks: Task-level outputs (if available)
    """
    try:
        ctx.info(f"Fetching outputs for workflow {workflow_id} in submission {submission_id}")

        response = fapi.get_workflow_outputs(
            workspace_namespace,
            workspace_name,
            submission_id,
            workflow_id,
        )

        if response.status_code == 404:
            raise ToolError(
                f"Workflow '{workflow_id}' not found in submission '{submission_id}' "
                f"for workspace '{workspace_namespace}/{workspace_name}'. "
                "Please verify the workflow ID and submission ID are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this workflow."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch workflow outputs (HTTP {response.status_code}). "
                "Please check the workspace and workflow IDs."
            )

        outputs = response.json()
        ctx.info(f"Successfully retrieved outputs for workflow {workflow_id}")

        return outputs

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching workflow outputs: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch outputs for workflow {workflow_id} in submission {submission_id}"
        )


@mcp.tool()
async def get_workflow_cost(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    submission_id: Annotated[str, "Submission identifier (UUID)"],
    workflow_id: Annotated[str, "Workflow identifier (UUID)"],
    ctx: Context,
) -> dict[str, Any]:
    """Get cost information for a workflow execution.

    Returns the compute cost for a workflow run. Cost is typically calculated based on
    VM usage, storage, and other Google Cloud Platform resources consumed during execution.

    Note: Cost information may not be immediately available after workflow completion.
    It can take several hours for GCP to process and report final costs.

    Common use cases:
    - Track workflow execution costs for budgeting
    - Compare costs across different workflow configurations
    - Optimize resource usage based on cost analysis

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        submission_id: The submission UUID containing this workflow
        workflow_id: The workflow UUID to get cost for

    Returns:
        Dictionary containing cost information. Typical structure:
        - cost: Estimated cost in USD
        - currency: Currency code (usually "USD")
        - costBreakdown: Detailed breakdown by task or resource type (if available)
        - status: Whether cost calculation is complete or pending
    """
    try:
        ctx.info(f"Fetching cost for workflow {workflow_id} in submission {submission_id}")

        response = fapi.get_workflow_cost(
            workspace_namespace,
            workspace_name,
            submission_id,
            workflow_id,
        )

        if response.status_code == 404:
            raise ToolError(
                f"Workflow '{workflow_id}' not found in submission '{submission_id}' "
                f"for workspace '{workspace_namespace}/{workspace_name}'. "
                "Please verify the workflow ID and submission ID are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this workflow."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch workflow cost (HTTP {response.status_code}). "
                "Please check the workspace and workflow IDs."
            )

        cost_data = response.json()
        ctx.info(f"Successfully retrieved cost information for workflow {workflow_id}")

        return cost_data

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching workflow cost: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch cost for workflow {workflow_id} in submission {submission_id}"
        )


# ===== Phase 3: Workflow Management Tools =====


@mcp.tool()
async def get_entities(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    entity_type: Annotated[str, "Entity type to retrieve (e.g., 'sample', 'participant')"],
    ctx: Context,
) -> dict[str, Any]:
    """Get all entities of a specific type from a Terra data table.

    Entities represent rows in Terra data tables and are used as workflow inputs.
    This tool retrieves all entities of a given type along with their attributes.

    Common use cases:
    - Retrieve sample/participant data for workflow submission
    - Verify entity attributes before launching workflows
    - Inspect data table contents

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        entity_type: The entity type to retrieve (matches data table name)

    Returns:
        Dictionary containing:
        - entity_type: The entity type requested
        - count: Number of entities returned
        - entities: List of entity objects with name, entityType, and attributes
    """
    try:
        ctx.info(
            f"Fetching entities of type '{entity_type}' from workspace "
            f"{workspace_namespace}/{workspace_name}"
        )

        response = fapi.get_entities(workspace_namespace, workspace_name, entity_type)

        if response.status_code == 404:
            raise ToolError(
                f"Workspace '{workspace_namespace}/{workspace_name}' or entity type "
                f"'{entity_type}' not found. Please verify the workspace and entity type are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this workspace."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch entities (HTTP {response.status_code}). "
                "Please check the workspace and entity type."
            )

        entities = response.json()
        ctx.info(f"Successfully retrieved {len(entities)} entities of type '{entity_type}'")

        return {
            "entity_type": entity_type,
            "count": len(entities),
            "entities": entities,
        }

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching entities: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch entities of type '{entity_type}' from workspace "
            f"{workspace_namespace}/{workspace_name}"
        )


@mcp.tool()
async def get_method_config(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    config_namespace: Annotated[str, "Method configuration namespace"],
    config_name: Annotated[str, "Method configuration name"],
    ctx: Context,
) -> dict[str, Any]:
    """Get a method configuration from a Terra workspace.

    Method configurations define how WDL workflows are executed, including:
    - Which WDL version/snapshot to use
    - Input mappings (linking WDL inputs to entity attributes or workspace data)
    - Output mappings (where to store WDL outputs)
    - Root entity type (what type of entities this workflow operates on)

    This is useful for:
    - Verifying the correct WDL version is configured before submission
    - Inspecting input/output mappings
    - Understanding workflow configuration before launching jobs

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        config_namespace: The namespace of the method configuration
        config_name: The name of the method configuration

    Returns:
        Dictionary containing method configuration details:
        - namespace: Configuration namespace
        - name: Configuration name
        - rootEntityType: Entity type this workflow operates on
        - methodRepoMethod: Details about the WDL method (namespace, name, version)
        - inputs: Input mappings (WDL input -> entity attribute)
        - outputs: Output mappings (WDL output -> entity attribute)
    """
    try:
        ctx.info(
            f"Fetching method configuration '{config_namespace}/{config_name}' "
            f"from workspace {workspace_namespace}/{workspace_name}"
        )

        response = fapi.get_workspace_config(
            workspace_namespace, workspace_name, config_namespace, config_name
        )

        if response.status_code == 404:
            raise ToolError(
                f"Method configuration '{config_namespace}/{config_name}' not found in "
                f"workspace '{workspace_namespace}/{workspace_name}'. "
                "Please verify the configuration namespace and name are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to view this configuration."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to fetch method configuration (HTTP {response.status_code}). "
                "Please check the workspace and configuration names."
            )

        config = response.json()
        ctx.info(
            f"Successfully retrieved method configuration '{config_name}' "
            f"(WDL version: {config.get('methodRepoMethod', {}).get('methodVersion', 'unknown')})"
        )

        return config

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching method configuration: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch method configuration '{config_namespace}/{config_name}' "
            f"from workspace {workspace_namespace}/{workspace_name}"
        )


@mcp.tool()
async def update_method_config(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    config_namespace: Annotated[str, "Method configuration namespace"],
    config_name: Annotated[str, "Method configuration name"],
    updates: Annotated[dict[str, Any], "Configuration updates to apply"],
    ctx: Context,
) -> dict[str, Any]:
    """Update a method configuration in a Terra workspace.

    This tool allows updating method configuration settings, including:
    - Changing WDL version (methodRepoMethod.methodVersion)
    - Modifying input/output mappings
    - Changing root entity type

    Common use case: Update WDL version to match development branch before testing.

    Example updates dict to change WDL version:
    {
        "methodRepoMethod": {
            "methodNamespace": "broad",
            "methodName": "MyWorkflow",
            "methodVersion": 6
        }
    }

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        config_namespace: The namespace of the method configuration
        config_name: The name of the method configuration
        updates: Dictionary with configuration fields to update

    Returns:
        Updated method configuration dictionary
    """
    try:
        ctx.info(
            f"Updating method configuration '{config_namespace}/{config_name}' "
            f"in workspace {workspace_namespace}/{workspace_name}"
        )

        response = fapi.update_workspace_config(
            workspace_namespace, workspace_name, config_namespace, config_name, updates
        )

        if response.status_code == 404:
            raise ToolError(
                f"Method configuration '{config_namespace}/{config_name}' not found in "
                f"workspace '{workspace_namespace}/{workspace_name}'. "
                "Please verify the configuration namespace and name are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to modify this configuration."
            )
        elif response.status_code != 200:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to update method configuration (HTTP {response.status_code}). "
                "Please check the workspace, configuration names, and update body."
            )

        updated_config = response.json()
        ctx.info(f"Successfully updated method configuration '{config_name}'")

        return updated_config

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error updating method configuration: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to update method configuration '{config_namespace}/{config_name}' "
            f"in workspace {workspace_namespace}/{workspace_name}"
        )


@mcp.tool()
async def copy_method_config(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    from_config_namespace: Annotated[str, "Source configuration namespace"],
    from_config_name: Annotated[str, "Source configuration name"],
    to_config_namespace: Annotated[str, "Destination configuration namespace"],
    to_config_name: Annotated[str, "Destination configuration name"],
    ctx: Context,
) -> dict[str, Any]:
    """Copy a method configuration within a Terra workspace.

    Creates a copy of an existing method configuration with a new name. This is useful for:
    - Creating development versions of production workflows
    - Testing configuration changes without modifying the original
    - Setting up parallel workflow variants

    The copied configuration will have the same WDL version, input/output mappings,
    and settings as the source configuration.

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        from_config_namespace: The namespace of the source configuration
        from_config_name: The name of the source configuration
        to_config_namespace: The namespace for the copied configuration
        to_config_name: The name for the copied configuration

    Returns:
        The newly created method configuration dictionary
    """
    try:
        ctx.info(
            f"Copying method configuration '{from_config_namespace}/{from_config_name}' "
            f"to '{to_config_namespace}/{to_config_name}' "
            f"in workspace {workspace_namespace}/{workspace_name}"
        )

        response = fapi.copy_config_from_repo(
            workspace_namespace,
            workspace_name,
            from_config_namespace,
            from_config_name,
            to_config_namespace,
            to_config_name,
        )

        if response.status_code == 404:
            raise ToolError(
                f"Source method configuration '{from_config_namespace}/{from_config_name}' "
                f"not found. Please verify the source configuration exists."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to copy configurations."
            )
        elif response.status_code == 409:
            raise ToolError(
                f"Destination configuration '{to_config_namespace}/{to_config_name}' "
                "already exists. Please choose a different name."
            )
        elif response.status_code not in [200, 201]:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to copy method configuration (HTTP {response.status_code}). "
                "Please check the configuration names and permissions."
            )

        new_config = response.json()
        ctx.info(
            f"Successfully copied method configuration to '{to_config_namespace}/{to_config_name}'"
        )

        return new_config

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error copying method configuration: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to copy method configuration from '{from_config_namespace}/{from_config_name}' "
            f"to '{to_config_namespace}/{to_config_name}'"
        )


@mcp.tool()
async def submit_workflow(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    config_namespace: Annotated[str, "Method configuration namespace"],
    config_name: Annotated[str, "Method configuration name"],
    entity_type: Annotated[str, "Entity type to run workflow on"],
    entity_name: Annotated[
        str | None, "Entity name to run workflow on (or None if using expression)"
    ],
    ctx: Context,
    expression: Annotated[
        str | None,
        "Optional entity expression for batch submission (e.g., 'this.samples')",
    ] = None,
    use_callcache: Annotated[bool, "Whether to use call caching (default: True)"] = True,
) -> dict[str, Any]:
    """Submit a workflow for execution in Terra.

    Launches a WDL workflow using a method configuration. Can submit for a single entity
    or use an entity expression for batch processing.

    Before submission, verify:
    1. Method configuration points to correct WDL version (use get_method_config)
    2. Entity data is correct (use get_entities)
    3. Input mappings are configured properly

    Common patterns:
    - Single entity: entity_name="sample_1", expression=None
    - Batch processing: entity_name=None, expression="this.samples"

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        config_namespace: The namespace of the method configuration
        config_name: The name of the method configuration
        entity_type: The entity type (must match config's rootEntityType)
        entity_name: The specific entity to run on (mutually exclusive with expression)
        expression: Entity expression for batch submission (mutually exclusive with entity_name)
        use_callcache: Whether to enable call caching for faster execution

    Returns:
        Dictionary containing submission details:
        - submissionId: Unique identifier for this submission
        - status: Initial submission status
        - submissionDate: When the submission was created
    """
    try:
        ctx.info(
            f"Submitting workflow '{config_namespace}/{config_name}' "
            f"for entity type '{entity_type}' "
            f"in workspace {workspace_namespace}/{workspace_name}"
        )

        response = fapi.create_submission(
            workspace_namespace,
            workspace_name,
            config_namespace,
            config_name,
            entity_type,
            entity_name,
            expression=expression,
            use_callcache=use_callcache,
        )

        if response.status_code == 404:
            raise ToolError(
                f"Method configuration '{config_namespace}/{config_name}' or entity not found. "
                "Please verify the configuration and entity exist."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to submit workflows."
            )
        elif response.status_code == 400:
            ctx.error(f"Bad request: {response.text}")
            raise ToolError(
                f"Failed to submit workflow (HTTP 400). Common issues: "
                "invalid entity type, missing inputs, or configuration errors. "
                f"Details: {response.text}"
            )
        elif response.status_code not in [200, 201]:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to submit workflow (HTTP {response.status_code}). "
                "Please check the configuration and entity."
            )

        submission = response.json()
        ctx.info(
            f"Successfully submitted workflow. Submission ID: {submission.get('submissionId')}"
        )

        return submission

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error submitting workflow: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to submit workflow '{config_namespace}/{config_name}' "
            f"in workspace {workspace_namespace}/{workspace_name}"
        )


@mcp.tool()
async def abort_submission(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    submission_id: Annotated[str, "Submission identifier (UUID) to abort"],
    ctx: Context,
) -> dict[str, Any]:
    """Abort a running workflow submission in Terra.

    Cancels a workflow submission and all its running workflows. This is useful for:
    - Stopping workflows with errors to save costs
    - Canceling workflows launched with incorrect parameters
    - Halting long-running jobs that are no longer needed

    Note: Aborting is a request and may not be immediate. Workflows already in final
    states (Succeeded, Failed) cannot be aborted.

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        submission_id: The unique identifier (UUID) of the submission to abort

    Returns:
        Dictionary containing:
        - submission_id: The submission that was aborted
        - status: Confirmation that abort was requested
    """
    try:
        ctx.info(
            f"Aborting submission '{submission_id}' "
            f"in workspace {workspace_namespace}/{workspace_name}"
        )

        response = fapi.abort_submission(workspace_namespace, workspace_name, submission_id)

        if response.status_code == 404:
            raise ToolError(
                f"Submission '{submission_id}' not found in workspace "
                f"'{workspace_namespace}/{workspace_name}'. "
                "Please verify the submission ID is correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to abort submissions."
            )
        elif response.status_code == 400:
            ctx.error(f"Bad request: {response.text}")
            raise ToolError(
                f"Failed to abort submission (HTTP 400). The submission may already be "
                f"completed or in a state that cannot be aborted. Details: {response.text}"
            )
        elif response.status_code not in [200, 204]:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to abort submission (HTTP {response.status_code}). "
                "Please check the submission ID and workspace."
            )

        ctx.info(f"Successfully requested abort for submission '{submission_id}'")

        return {
            "submission_id": submission_id,
            "status": "abort_requested",
            "message": "Abort request submitted. Workflows will be canceled shortly.",
        }

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error aborting submission: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to abort submission '{submission_id}' "
            f"in workspace {workspace_namespace}/{workspace_name}"
        )


# ===== Phase 4: Data Management Tools =====


@mcp.tool()
async def upload_entities(
    workspace_namespace: Annotated[str, "Terra workspace namespace"],
    workspace_name: Annotated[str, "Terra workspace name"],
    entity_data: Annotated[
        list[dict[str, Any]],
        "List of entities to upload, each with 'name', 'entityType', and 'attributes' fields",
    ],
    ctx: Context,
) -> dict[str, Any]:
    """Upload or update entity data in a Terra workspace data table.

    Entities are rows in Terra data tables used as workflow inputs. This tool allows
    you to add new entities or update existing ones.

    Each entity must have:
    - name: Unique identifier for the entity (entity ID)
    - entityType: Type of entity (e.g., 'sample', 'participant', 'sample_set')
    - attributes: Dictionary of attribute name-value pairs

    Example entity_data:
    [
        {
            "name": "sample_1",
            "entityType": "sample",
            "attributes": {
                "sample_id": "S001",
                "participant": "P001",
                "bam_file": "gs://bucket/sample1.bam"
            }
        },
        {
            "name": "sample_2",
            "entityType": "sample",
            "attributes": {
                "sample_id": "S002",
                "participant": "P002",
                "bam_file": "gs://bucket/sample2.bam"
            }
        }
    ]

    Common use cases:
    - Upload sample metadata for workflow execution
    - Update entity attributes with new values
    - Prepare data tables before workflow submission

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        entity_data: List of entities to upload (each with name, entityType, attributes)

    Returns:
        Dictionary containing:
        - success: Whether the upload succeeded
        - entity_count: Number of entities uploaded
        - entity_type: The entity type that was uploaded
    """
    try:
        # Validate entity_data
        if not entity_data:
            raise ToolError(
                "Entity data cannot be empty. Please provide at least one entity to upload."
            )

        # Validate entity format
        for i, entity in enumerate(entity_data):
            if "name" not in entity:
                raise ToolError(
                    f"Entity at index {i} is missing required field 'name'. "
                    "Each entity must have 'name', 'entityType', and 'attributes'."
                )
            if "entityType" not in entity:
                raise ToolError(
                    f"Entity at index {i} (name='{entity.get('name')}') is missing required "
                    "field 'entityType'. Each entity must have 'name', 'entityType', and 'attributes'."
                )
            if "attributes" not in entity:
                raise ToolError(
                    f"Entity at index {i} (name='{entity.get('name')}') is missing required "
                    "field 'attributes'. Each entity must have 'name', 'entityType', and 'attributes'."
                )

        # Get entity type from first entity (all should be same type)
        entity_type = entity_data[0]["entityType"]

        ctx.info(
            f"Uploading {len(entity_data)} entities of type '{entity_type}' "
            f"to workspace {workspace_namespace}/{workspace_name}"
        )

        response = fapi.upload_entities(
            workspace_namespace,
            workspace_name,
            entity_data,
        )

        if response.status_code == 404:
            raise ToolError(
                f"Workspace '{workspace_namespace}/{workspace_name}' not found. "
                "Please verify the workspace namespace and name are correct."
            )
        elif response.status_code == 403:
            raise ToolError(
                f"Access denied to workspace '{workspace_namespace}/{workspace_name}'. "
                "You may not have permission to upload entities to this workspace."
            )
        elif response.status_code == 400:
            ctx.error(f"Bad request: {response.text}")
            raise ToolError(
                f"Failed to upload entities (HTTP 400). Common issues: "
                "invalid entity format, duplicate names, or invalid attribute values. "
                f"Details: {response.text}"
            )
        elif response.status_code not in [200, 201]:
            ctx.error(f"FISS API returned status {response.status_code}: {response.text}")
            raise ToolError(
                f"Failed to upload entities (HTTP {response.status_code}). "
                "Please check the entity data format and workspace permissions."
            )

        ctx.info(
            f"Successfully uploaded {len(entity_data)} entities of type '{entity_type}' "
            f"to {workspace_namespace}/{workspace_name}"
        )

        return {
            "success": True,
            "entity_count": len(entity_data),
            "entity_type": entity_type,
            "message": f"Successfully uploaded {len(entity_data)} {entity_type} entities",
        }

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error uploading entities: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to upload entities to workspace {workspace_namespace}/{workspace_name}"
        )


# ===== Server Entry Point =====


if __name__ == "__main__":
    # Run server with stdio transport (compatible with Claude Desktop)
    mcp.run()
