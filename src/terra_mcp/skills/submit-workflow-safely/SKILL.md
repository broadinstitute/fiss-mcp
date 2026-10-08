---
description: Submit WDL workflows to Terra safely. Use before launching workflows to verify configuration, validate inputs, and choose between single-entity and batch processing.
---

# Submitting Workflows Safely

This skill teaches you how to verify workflow configuration and safely submit workflows to Terra.

## Pre-Submission Checklist

Before submitting a workflow, verify these three things:

### 1. Verify Method Configuration Points to Correct WDL Version

```
get_method_config(workspace_namespace, workspace_name, config_namespace, config_name)
```

Check the `methodRepoMethod` section for:
- `methodNamespace`: The WDL repository namespace
- `methodName`: The workflow name
- `methodVersion`: The snapshot/version number

**Common issue:** Configuration points to an old WDL version instead of the latest.

### 2. Verify Entity Data is Correct

`get_entities` returns **one page** (100 rows by default), so never use a bare
call to decide whether an entity exists: on a table with more rows than one
page, a real entity looks missing. Use `entity_name`, which is an exact lookup
by the table's id, and ask only for the attributes you are about to check.

```
get_entities(
    workspace_namespace, workspace_name, entity_type,
    entity_name="<entity_name>",
    columns=["<attribute>", "<attribute>"],
)
```

Do not use `filter_terms` for this. It is a substring search over the row, so a
miss does not mean the entity is absent. `entity_name` returns exactly 0 or 1
rows, and 0 is a real answer rather than an error.

Confirm from the response:
- `count` is 1, and the row is in `entities`
- The attributes you need are populated
- File paths (GCS URLs) look right

Attribute names come from `get_workspace_data_tables`, which lists each table's
`columns` alongside its row count. Omitting `columns` returns every attribute
and is refused outright above `max_response_bytes` on a wide table; see the
manage-context-size skill.

### 3. Verify Input Mappings are Configured

In the method configuration (from step 1), check:
- `inputs`: Maps WDL input variables to entity attributes or literal values
- `outputs`: Maps WDL outputs to entity attributes for storage
- `rootEntityType`: Must match the entity type you're submitting

## Submission Patterns

### Single Entity Submission

Submit a workflow for one specific entity:

```
submit_workflow(
    workspace_namespace="my-namespace",
    workspace_name="my-workspace",
    config_namespace="my-config-ns",
    config_name="my-workflow-config",
    entity_type="sample",
    entity_name="sample_001",
    use_callcache=True
)
```

**Use when:** Testing a workflow, debugging with a specific sample, or processing individual items.

### Batch Processing with Entity Expression

Submit a workflow for multiple entities using an expression:

```
submit_workflow(
    workspace_namespace="my-namespace",
    workspace_name="my-workspace",
    config_namespace="my-config-ns",
    config_name="my-workflow-config",
    entity_type="sample_set",
    entity_name="my_sample_set",
    expression="this.samples",
    use_callcache=True
)
```

**Use when:** Processing multiple samples defined in a sample set.

**Note:** When using expression, `entity_name` should be the set/collection entity, and `expression` specifies how to iterate over its members.

## Call Caching

The `use_callcache` parameter (default: True) enables Cromwell call caching:

- **Enabled (True):** If a task has already run with identical inputs, outputs are reused. Saves time and money on re-runs.
- **Disabled (False):** Forces all tasks to run from scratch. Use when debugging or when you need fresh outputs.

## Common Issues and Solutions

### Issue: "Entity not found"
- Verify the entity exists: `get_entities(..., entity_name="<entity_name>")` and check `count` is 1. A bare `get_entities(...)` returns only the first page, so it cannot tell you an entity is absent, and `filter_terms` is a substring search rather than an id lookup.
- Check entity type matches `rootEntityType` in method config
- Ensure entity name is spelled correctly

### Issue: "Missing required input"
- Check method config inputs mapping
- Verify entity has all required attributes
- Some inputs may need literal values in the config

### Issue: "Workflow version mismatch"
- Use `get_method_config()` to check current version
- Use `update_method_config()` to change WDL version

### Issue: "Permission denied"
- Ensure server was started with `--allow-writes` flag
- Verify you have write access to the workspace

## Updating WDL Version Before Submission

If you need to test a new WDL version:

```
# Check current version
get_method_config(workspace_namespace, workspace_name, config_namespace, config_name)

# Update to new version
update_method_config(
    workspace_namespace, workspace_name, config_namespace, config_name,
    updates={
        "methodRepoMethod": {
            "methodNamespace": "broad",
            "methodName": "MyWorkflow",
            "methodVersion": 6
        }
    }
)

# Submit with new version
submit_workflow(...)
```

## Creating a Test Configuration

To test without modifying production configuration:

```
# Copy existing configuration
copy_method_config(
    workspace_namespace, workspace_name,
    from_config_namespace="production",
    from_config_name="my-workflow",
    to_config_namespace="dev",
    to_config_name="my-workflow-test"
)

# Update the copy with new version
update_method_config(..., config_name="my-workflow-test", ...)

# Submit using test configuration
submit_workflow(..., config_name="my-workflow-test", ...)
```

## Monitoring After Submission

After submitting, you'll receive a `submissionId`. Monitor it with:

```
get_submission_status(workspace_namespace, workspace_name, submission_id)
```

Check periodically until status is no longer "Submitted" or "Running".
