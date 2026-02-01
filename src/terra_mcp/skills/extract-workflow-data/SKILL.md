---
description: Extract specific data from Cromwell workflow metadata efficiently. Use when you need task outputs, runtime attributes, or specific fields without loading full 100K+ token metadata.
---

# Extracting Workflow Data Efficiently

This skill teaches you how to extract specific data from Cromwell workflow metadata without loading the entire 100K+ token metadata blob into your context.

## Recommended Usage Pattern

### Step 1: Start with Summary Mode (Default)

```
get_job_metadata(workspace_namespace, workspace_name, submission_id, workflow_id)
```

Summary mode returns a structured, context-efficient summary (~1-2K tokens) including:
- Workflow status and timing
- Task counts by status
- Failed task details with errors
- Execution summary

This gives you the lay of the land without context exhaustion.

### Step 2: Extract Specific Data with Extract Mode

Use semantic parameters to get exactly what you need:

#### Get a Specific Task Output

```
get_job_metadata(
    workspace_namespace, workspace_name, submission_id, workflow_id,
    mode="extract",
    task_name="illumina_demux",
    output_name="commonBarcodes"
)
```

#### Get Output from a Specific Shard

For scattered tasks with multiple shards:

```
get_job_metadata(
    workspace_namespace, workspace_name, submission_id, workflow_id,
    mode="extract",
    task_name="align_reads",
    shard_index=5,
    output_name="aligned_bam"
)
```

#### Get Runtime Attributes for All Tasks

Use wildcards with dot-path notation:

```
get_job_metadata(
    workspace_namespace, workspace_name, submission_id, workflow_id,
    mode="extract",
    field_path="calls.*.runtimeAttributes"
)
```

This returns a dictionary mapping task names to their runtime attributes.

## Dot-Path Syntax Reference

The `field_path` parameter supports flexible extraction using dot notation:

| Syntax | Meaning | Example |
|--------|---------|---------|
| `key.subkey` | Nested access | `calls.task1.outputs` |
| `key[N]` | Array indexing | `calls.task1[0].outputs` |
| `key.*` | Wildcard (all keys) | `calls.*.executionStatus` |

### Examples

```
# Get execution status of all tasks
field_path="calls.*.executionStatus"

# Get first shard's outputs for a specific task
field_path="calls.my_task[0].outputs"

# Get all runtime attributes
field_path="calls.*.runtimeAttributes"

# Get preemptible setting across all tasks
field_path="calls.*.runtimeAttributes.preemptible"

# Get backend status
field_path="calls.*[0].backendStatus"
```

## Multiple Extractions

If you need multiple pieces of data, make multiple extract calls rather than trying to get everything at once. Each call returns only what you need:

```python
# Call 1: Get specific output
get_job_metadata(..., mode="extract", task_name="task1", output_name="result")

# Call 2: Get runtime attributes
get_job_metadata(..., mode="extract", field_path="calls.task1[0].runtimeAttributes")

# Call 3: Get another task's output
get_job_metadata(..., mode="extract", task_name="task2", output_name="file")
```

This is more context-efficient than loading full metadata.

## Error Handling

When extraction fails, the tool provides helpful error messages:

**Task not found:**
```
Task 'xyz' not found. Available tasks: ['workflow.task1', 'workflow.task2', ...]
```

**Output not found:**
```
Output 'xyz' not found for task 'task1'. Available outputs: ['file', 'count', 'summary']
```

**Shard not found:**
```
Shard 5 not found for task 'task1'. Available shards: [0, 1, 2, 3]
```

## When to Use Each Mode

| Scenario | Mode | Parameters |
|----------|------|------------|
| Initial exploration | `summary` | (default) |
| Get specific task output | `extract` | `task_name`, `output_name` |
| Get scattered task shard output | `extract` | `task_name`, `shard_index`, `output_name` |
| Compare settings across tasks | `extract` | `field_path` with wildcard |
| Get deep nested field | `extract` | `field_path` with dot notation |

## Anti-Patterns

**Never do this:**
- Repeatedly call get_job_metadata without specifying what you need
- Try to extract everything in one call

**Do this instead:**
- Start with summary mode to understand the workflow
- Make targeted extract calls for specific data you need
- Use wildcards to batch-extract across tasks
