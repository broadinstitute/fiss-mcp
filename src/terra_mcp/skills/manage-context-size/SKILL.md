---
description: Prevent LLM context exhaustion when working with large Terra data. Use with scattered workflows (50+ shards), large data tables (100+ entities), or verbose metadata.
---

# Managing Context Size

This skill teaches you how to avoid context exhaustion when working with large Terra datasets, scattered workflows, and verbose Cromwell metadata.

## Context Size Risks

These operations can exhaust your context window:

| Operation | Risk Level | Potential Size |
|-----------|------------|----------------|
| `get_job_metadata` (full) | **CRITICAL** | 100K+ tokens per workflow |
| `get_workflow_logs` with many shards | **HIGH** | 25K+ tokens per task log |
| `get_entities` for large tables | **HIGH** | 10K+ tokens for 100 entities |
| `get_submission_status` with `include_inputs=True` | **MEDIUM** | 30K+ tokens for 9 workflows |

## Safe Patterns

### 1. Always Use Summary Mode for Metadata

```
# SAFE: Returns ~1-2K tokens
get_job_metadata(workspace_namespace, workspace_name, submission_id, workflow_id)

# DANGEROUS: Can return 100K+ tokens
# (There is no "full" mode - the tool protects you)
```

Summary mode is the default. It returns structured, actionable information without the verbose raw metadata.

### 2. Get Log URLs Before Fetching Content

For scattered workflows (50+ shards), fetching all logs can quickly exhaust context.

```
# Step 1: Get URLs only (fast, small response)
get_workflow_logs(
    workspace_namespace, workspace_name, submission_id, workflow_id,
    fetch_content=False  # Default
)

# Step 2: Identify which specific tasks failed
get_job_metadata(..., mode="summary")

# Step 3: Fetch content only for failed tasks you need
# (Consider fetching logs one at a time for scattered workflows)
```

### 3. Check Table Sizes Before Fetching Entities

```
# Step 1: Check row counts
get_workspace_data_tables(workspace_namespace, workspace_name)
# Response: {"tables": [{"name": "sample", "count": 5000}, ...]}

# Step 2: If count > 100, reconsider whether you need all entities
# Often, specific entity names from workflow inputs are sufficient
```

### 4. Limit Workflow Count in Submission Status

```
# Default: Returns first 10 workflows (manageable)
get_submission_status(workspace_namespace, workspace_name, submission_id)

# For large submissions, the default limit protects you
# Only use max_workflows=0 if you truly need all workflow details
```

### 5. Exclude Input Resolutions (Default Behavior)

```
# Default: Excludes inputResolutions (94% size reduction)
get_submission_status(workspace_namespace, workspace_name, submission_id)

# Only include inputs if you need to debug input values
get_submission_status(..., include_inputs=True)  # Much larger response
```

## Progressive Disclosure Strategy

When investigating workflows, follow this pattern:

1. **Start broad, go narrow:**
   - Begin with summaries and overviews
   - Drill into specific items only when needed

2. **Identify targets first:**
   - Get workflow IDs before fetching details
   - Get failed task names before fetching logs
   - Get entity names from workflow inputs, not full table dumps

3. **Fetch content last:**
   - URLs and summaries first
   - Actual content only for items you're debugging

## Context Budget Estimation

Rough token estimates for planning:

| Response Type | Approximate Tokens |
|--------------|-------------------|
| Submission status (10 workflows, no inputs) | 1,500 |
| Submission status (10 workflows, with inputs) | 20,000 |
| Job metadata summary | 1,500 |
| Workflow logs (URLs only) | 500 per task |
| Workflow logs (with content, truncated) | 8,000 per task |
| Entity table (100 entities) | 10,000 |
| Batch job status | 2,500 |

## When Large Responses Are Needed

Sometimes you genuinely need large data. In these cases:

1. **Process incrementally:** Request data in batches
2. **Extract specific fields:** Use `get_job_metadata(..., mode="extract", field_path="...")`
3. **Work offline:** For very large datasets, consider extracting to files and analyzing externally

## Anti-Patterns to Avoid

| Bad Pattern | Good Alternative |
|-------------|------------------|
| Fetch all entities for a 5000-row table | Get specific entity names from workflow inputs |
| Fetch all workflow logs in scattered workflow | Get URLs, identify failures, fetch specific logs |
| Include inputs for all workflows | Use default (exclude inputs) unless debugging inputs |
| Request max_workflows=0 for 500-workflow submission | Use default limit, request specific workflow details as needed |

## Quick Reference: Safe Defaults

All these tools have context-safe defaults:

- `get_job_metadata`: Summary mode by default
- `get_workflow_logs`: URLs only by default (fetch_content=False)
- `get_submission_status`: 10 workflows max, no inputs by default
- Log truncation: First 5K + last 20K chars when fetching content
