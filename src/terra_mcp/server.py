"""Terra.Bio MCP Server

MCP server for interacting with Terra.Bio workspaces via the FISS API.
Provides tools for listing workspaces, querying data tables, and monitoring workflow submissions.
"""

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from firecloud import api as fapi

# Initialize MCP server
mcp = FastMCP(
    "Terra.Bio MCP Server",
    instructions=(
        "Interact with Terra.Bio workspaces and workflows via FISS API. "
        "Monitor WDL pipeline runs, query data tables, and check submission status."
    ),
    mask_error_details=True,  # Hide internal errors in production
)


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
        "Optional list of metadata keys to include (returns only these keys)",
    ] = None,
    exclude_keys: Annotated[
        list[str] | None,
        "Optional list of metadata keys to exclude (omits these keys)",
    ] = None,
) -> dict[str, Any]:
    """Get detailed Cromwell metadata for a specific workflow/job.

    Returns comprehensive execution metadata including task-level details, execution status,
    timing information, and references to log files. This is the Cromwell metadata JSON.

    Use include_keys or exclude_keys to filter the response for specific information:
    - include_keys=['status', 'failures'] - Get only status and failure information
    - exclude_keys=['calls'] - Omit detailed call information to reduce response size

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        submission_id: The submission UUID containing this workflow
        workflow_id: The workflow UUID to get metadata for
        include_keys: Optional list of metadata keys to include
        exclude_keys: Optional list of metadata keys to exclude

    Returns:
        Dictionary containing Cromwell workflow metadata (structure depends on filtering)
    """
    try:
        ctx.info(f"Fetching metadata for workflow {workflow_id} in submission {submission_id}")

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
) -> dict[str, Any]:
    """Get workflow execution log locations and task status.

    Retrieves stderr and stdout log file locations (Google Cloud Storage URLs) from the
    workflow metadata for each task execution. The actual log content is stored in GCS
    and can be fetched separately using the returned URLs.

    This tool is useful for:
    - Identifying which tasks have logs available
    - Getting the GCS paths to log files for debugging
    - Seeing execution status and retry attempts for each task

    Args:
        workspace_namespace: The billing namespace of the workspace
        workspace_name: The name of the workspace
        submission_id: The submission UUID containing this workflow
        workflow_id: The workflow UUID to get logs for

    Returns:
        Dictionary containing:
        - workflow_id: The workflow UUID
        - workflow_name: Name of the workflow
        - status: Workflow execution status
        - logs: Dictionary mapping task names to their log URLs and execution info
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
                stderr = execution.get("stderr", "")
                stdout = execution.get("stdout", "")

                # Create unique task key for multiple attempts
                task_key = f"{task_name}[{i}]" if len(task_executions) > 1 else task_name

                logs_by_task[task_key] = {
                    "stderr_url": stderr,
                    "stdout_url": stdout,
                    "status": execution.get("executionStatus", "Unknown"),
                    "attempt": execution.get("attempt", 1),
                    "shard": execution.get("shardIndex", -1),
                }

        ctx.info(f"Successfully retrieved log locations for {len(logs_by_task)} tasks")

        return {
            "workflow_id": workflow_id,
            "workflow_name": metadata.get("workflowName", ""),
            "status": metadata.get("status", "Unknown"),
            "task_count": len(logs_by_task),
            "logs": logs_by_task,
        }

    except ToolError:
        raise
    except Exception as e:
        ctx.error(f"Unexpected error fetching workflow logs: {type(e).__name__}: {e}")
        raise ToolError(
            f"Failed to fetch logs for workflow {workflow_id} in submission {submission_id}"
        )


# ===== Server Entry Point =====


if __name__ == "__main__":
    # Run server with stdio transport (compatible with Claude Desktop)
    mcp.run()
