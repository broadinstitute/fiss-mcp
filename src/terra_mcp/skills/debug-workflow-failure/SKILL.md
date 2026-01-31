---
description: Debug failed Terra/Cromwell workflow submissions. Use when analyzing failed submissions, identifying error patterns, or troubleshooting infrastructure issues like docker pull failures, preemption, or OOM.
---

# Debugging Workflow Failures in Terra

This skill teaches you how to efficiently debug failed Terra workflow submissions without exhausting your context window.

## Efficient Debugging Sequence

Follow this sequence to minimize context usage while maximizing diagnostic information:

### Step 1: Get Submission Overview

```
get_submission_status(workspace_namespace, workspace_name, submission_id)
```

This returns:
- Overall submission status
- Count of workflows by status (Succeeded, Failed, Running)
- List of workflow IDs with their individual statuses

**What to look for:** Identify failed workflow IDs from the `status_summary` and `workflows` array.

### Step 2: Get Failed Task Details (~1-2K tokens)

```
get_job_metadata(workspace_namespace, workspace_name, submission_id, workflow_id, mode="summary")
```

The summary mode returns a context-efficient view with:
- Workflow status and timing
- Task counts by execution status
- **Failed task details with error messages**
- Log URLs for failed tasks

**What to look for:** The `failed_tasks` array contains task names, shard indices, error messages, and log URLs.

### Step 3: Get Log URLs (fast, small response)

```
get_workflow_logs(workspace_namespace, workspace_name, submission_id, workflow_id, fetch_content=False)
```

Returns GCS URLs for stderr/stdout without fetching content. Use this to identify which logs exist before deciding what to fetch.

### Step 4: Fetch Specific Failed Task Logs

Only fetch logs for tasks you need to debug:

```
get_workflow_logs(workspace_namespace, workspace_name, submission_id, workflow_id, fetch_content=True)
```

Logs are automatically truncated (first 5K + last 20K chars) to preserve error messages while staying context-efficient.

### Step 5: Check Infrastructure Issues (if needed)

If stderr logs don't explain the failure, check for infrastructure issues:

```
get_batch_job_status(workspace_namespace, workspace_name, submission_id, workflow_id, task_name)
```

**Signs you need this tool:**
- Task failed but stderr is empty or very short
- Error says "The job was stopped before the command finished"
- Batch reports exit code 0 but task is marked Failed
- Task failed instantly (0 seconds runtime)

**What this tool detects:**
- Docker image pull failures (rate limits, not found, auth errors)
- VM preemption events
- OOM kills (exit code 137)
- Resource/quota exhaustion
- Network connectivity issues

## Common Failure Patterns

### Pattern: Out of Memory (OOM)
- **Symptoms:** Exit code 137, "Killed" in logs, or OOM detected by get_batch_job_status
- **Fix:** Increase memory in WDL runtime section: `memory: "32 GB"`

### Pattern: Disk Exhaustion
- **Symptoms:** "No space left on device" in stderr
- **Fix:** Increase disk size in WDL runtime: `disks: "local-disk 200 HDD"`

### Pattern: Docker Pull Failure
- **Symptoms:** get_batch_job_status shows docker_pull_failure or docker_pull_rate_limit
- **Fix:** Use authenticated pulls, switch to private registry, or wait and retry

### Pattern: Preemption
- **Symptoms:** get_batch_job_status shows preemption issue
- **Note:** Task will be automatically retried. Consider non-preemptible VMs for time-sensitive work

### Pattern: Input Data Errors
- **Symptoms:** Specific samples fail with parsing/format errors
- **Fix:** Validate input files before resubmitting

## Categorizing Multiple Failures

When a submission has many failures, group them by pattern:

1. Get all failed workflow IDs from `get_submission_status`
2. For each failed workflow, call `get_job_metadata(mode="summary")`
3. Group failures by error message similarity
4. Report categories with counts and recommendations

## Anti-Patterns to Avoid

**Never do this:**
- Fetch full workflow metadata (100K+ tokens per workflow)
- Fetch all logs for all tasks in a scattered workflow
- Make many sequential calls when one call provides enough info

**Do this instead:**
- Use summary mode by default
- Check log URLs before fetching content
- Use get_batch_job_status only when stderr doesn't explain the failure
