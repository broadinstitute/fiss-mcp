---
description: Navigate and debug WDL subworkflows in Terra. Use when a workflow calls nested subworkflows and you need to find subworkflow IDs or debug nested executions.
---

# Navigating Subworkflows

This skill teaches you how to work with nested WDL subworkflows in Terra. When a WDL workflow calls another workflow (a subworkflow), each subworkflow gets its own workflow ID and can be inspected independently.

## Understanding Subworkflows

In WDL, a workflow can call other workflows as tasks. When this happens:

1. **Parent workflow:** Has its own workflow ID and metadata
2. **Subworkflow:** Gets a separate workflow ID, visible in parent metadata
3. **Each subworkflow:** Can be queried independently using Terra tools

## Finding Subworkflow IDs

Subworkflow IDs are stored in the parent workflow's metadata under:
```
calls.<subworkflow_name>[*].subWorkflowId
```

### Step 1: Get Parent Workflow Metadata

```
get_job_metadata(
    workspace_namespace, workspace_name, submission_id, workflow_id,
    mode="extract",
    field_path="calls.*.subWorkflowId"
)
```

This returns subworkflow IDs for all task calls that are subworkflows.

### Step 2: Identify Which Tasks Are Subworkflows

Not all tasks are subworkflows. To check:

```
get_job_metadata(
    workspace_namespace, workspace_name, submission_id, workflow_id,
    mode="summary"
)
```

In the summary, subworkflow tasks will have execution entries with `subWorkflowId` fields.

### Alternative: Extract Specific Subworkflow ID

If you know the subworkflow task name:

```
get_job_metadata(
    workspace_namespace, workspace_name, submission_id, workflow_id,
    mode="extract",
    task_name="my_subworkflow_call",
    field_path="subWorkflowId"
)
```

## Debugging Subworkflows

Once you have a subworkflow ID, use it directly with any workflow tool:

### Get Subworkflow Summary

```
get_job_metadata(
    workspace_namespace, workspace_name, submission_id,
    workflow_id="<subworkflow-id>",  # Use subworkflow ID here
    mode="summary"
)
```

### Get Subworkflow Logs

```
get_workflow_logs(
    workspace_namespace, workspace_name, submission_id,
    workflow_id="<subworkflow-id>",
    fetch_content=True
)
```

### Get Subworkflow Outputs

```
get_workflow_outputs(
    workspace_namespace, workspace_name, submission_id,
    workflow_id="<subworkflow-id>"
)
```

### Get Subworkflow Cost

```
get_workflow_cost(
    workspace_namespace, workspace_name, submission_id,
    workflow_id="<subworkflow-id>"
)
```

### Debug Subworkflow Task Infrastructure

```
get_batch_job_status(
    workspace_namespace, workspace_name, submission_id,
    workflow_id="<subworkflow-id>",
    task_name="task_within_subworkflow"
)
```

## Nested Subworkflows

Subworkflows can themselves call subworkflows, creating multiple levels of nesting:

```
Parent Workflow
  └─ Subworkflow A (has own workflow ID)
       └─ Subworkflow A.1 (has own workflow ID)
       └─ Subworkflow A.2 (has own workflow ID)
  └─ Subworkflow B (has own workflow ID)
```

To navigate deeply nested workflows:

1. Start at the parent workflow
2. Extract subworkflow IDs from its metadata
3. Query each subworkflow as needed
4. If that subworkflow has its own subworkflows, repeat

## Example: Debugging a Failed Subworkflow Task

```python
# 1. Get parent workflow summary to see which subworkflow failed
get_job_metadata(workspace_namespace, workspace_name, submission_id, parent_workflow_id)
# Response shows: "SubWorkflowA" task failed

# 2. Extract the subworkflow ID
get_job_metadata(
    workspace_namespace, workspace_name, submission_id, parent_workflow_id,
    mode="extract",
    task_name="SubWorkflowA",
    shard_index=0,
    output_name=None,
    field_path="subWorkflowId"
)
# Returns: subworkflow_id = "abc-123-def"

# 3. Get the subworkflow's summary to find the actual failed task
get_job_metadata(
    workspace_namespace, workspace_name, submission_id,
    workflow_id="abc-123-def"  # Use subworkflow ID
)
# Response shows: "process_data" task within subworkflow failed

# 4. Get logs for the failed task within the subworkflow
get_workflow_logs(
    workspace_namespace, workspace_name, submission_id,
    workflow_id="abc-123-def",
    fetch_content=True
)
```

## Key Points

1. **Subworkflows have their own workflow IDs** - they're not just nested metadata
2. **Use subworkflow IDs directly** - all workflow tools accept them
3. **The submission_id stays the same** - subworkflows are part of the same submission
4. **Task names in subworkflows are scoped** - they may differ from parent workflow tasks
