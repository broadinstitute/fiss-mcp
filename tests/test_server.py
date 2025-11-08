"""Tests for Terra.Bio MCP Server

Basic test suite to verify server initialization, tool registration,
and error handling with mocked FISS API calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from terra_mcp.server import mcp


@pytest.fixture
def enable_writes():
    """Pytest fixture to temporarily enable write operations for testing"""
    import terra_mcp.server as server_module

    original_allow_writes = server_module.ALLOW_WRITES
    server_module.ALLOW_WRITES = True
    yield
    server_module.ALLOW_WRITES = original_allow_writes


class TestServerInitialization:
    """Test basic server setup and configuration"""

    def test_server_exists(self):
        """Verify MCP server instance exists"""
        assert mcp is not None
        assert mcp.name == "Terra.Bio MCP Server"

    def test_server_has_tools(self):
        """Verify all Phase 1, Phase 2, Phase 3, and Phase 4 tools are registered"""
        # Get registered tools via MCP's internal registry
        # Note: FastMCP uses decorators to register tools
        tools = mcp._tool_manager._tools
        tool_names = {name for name in tools.keys()}

        # Verify all Phase 1 tools are present
        assert "list_workspaces" in tool_names
        assert "get_workspace_data_tables" in tool_names
        assert "get_submission_status" in tool_names
        assert "get_job_metadata" in tool_names
        assert "get_workflow_logs" in tool_names

        # Verify all Phase 2 tools are present
        assert "list_submissions" in tool_names
        assert "get_workflow_outputs" in tool_names
        assert "get_workflow_cost" in tool_names

        # Verify all Phase 3 tools are present
        assert "get_entities" in tool_names
        assert "get_method_config" in tool_names
        assert "update_method_config" in tool_names
        assert "copy_method_config" in tool_names
        assert "submit_workflow" in tool_names
        assert "abort_submission" in tool_names

        # Verify all Phase 4 tools are present
        assert "upload_entities" in tool_names


class TestListWorkspaces:
    """Test list_workspaces tool"""

    @pytest.mark.asyncio
    async def test_list_workspaces_success(self):
        """Test successful workspace listing"""
        # Mock FISS API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "workspace": {
                    "namespace": "test-namespace",
                    "name": "test-workspace",
                    "createdBy": "user@example.com",
                    "createdDate": "2024-01-01T00:00:00Z",
                }
            },
            {
                "workspace": {
                    "namespace": "another-namespace",
                    "name": "another-workspace",
                    "createdBy": "user2@example.com",
                    "createdDate": "2024-02-01T00:00:00Z",
                }
            },
        ]

        with patch("terra_mcp.server.fapi.list_workspaces", return_value=mock_response):
            # Access the underlying function from the FunctionTool wrapper
            list_workspaces_fn = mcp._tool_manager._tools["list_workspaces"].fn

            # Create mock context
            ctx = MagicMock()
            result = await list_workspaces_fn(ctx)

            # Verify result structure
            assert len(result) == 2
            assert result[0]["namespace"] == "test-namespace"
            assert result[0]["name"] == "test-workspace"
            assert result[0]["created_by"] == "user@example.com"
            assert result[1]["namespace"] == "another-namespace"

    @pytest.mark.asyncio
    async def test_list_workspaces_api_error(self):
        """Test handling of FISS API errors"""
        from fastmcp.exceptions import ToolError

        # Mock failed API response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("terra_mcp.server.fapi.list_workspaces", return_value=mock_response):
            # Access the underlying function from the FunctionTool wrapper
            list_workspaces_fn = mcp._tool_manager._tools["list_workspaces"].fn

            ctx = MagicMock()

            # Should raise ToolError with actionable message
            with pytest.raises(ToolError) as exc_info:
                await list_workspaces_fn(ctx)

            assert "Failed to fetch workspaces" in str(exc_info.value)
            assert "500" in str(exc_info.value)


class TestGetWorkspaceDataTables:
    """Test get_workspace_data_tables tool"""

    @pytest.mark.asyncio
    async def test_get_data_tables_success(self):
        """Test successful data table retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"name": "participant", "count": 100},
            {"name": "sample", "count": 500},
        ]

        with patch("terra_mcp.server.fapi.list_entity_types", return_value=mock_response):
            # Access the underlying function from the FunctionTool wrapper
            get_workspace_data_tables_fn = mcp._tool_manager._tools["get_workspace_data_tables"].fn

            ctx = MagicMock()
            result = await get_workspace_data_tables_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
            )

            assert result["workspace"] == "test-ns/test-ws"
            assert len(result["tables"]) == 2
            assert result["tables"][0]["name"] == "participant"
            assert result["tables"][0]["count"] == 100
            assert result["tables"][1]["name"] == "sample"
            assert result["tables"][1]["count"] == 500

    @pytest.mark.asyncio
    async def test_get_data_tables_workspace_not_found(self):
        """Test handling of non-existent workspace"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.list_entity_types", return_value=mock_response):
            # Access the underlying function from the FunctionTool wrapper
            get_workspace_data_tables_fn = mcp._tool_manager._tools["get_workspace_data_tables"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_workspace_data_tables_fn(
                    workspace_namespace="nonexistent",
                    workspace_name="workspace",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg
            assert "nonexistent/workspace" in error_msg

    @pytest.mark.asyncio
    async def test_get_data_tables_access_denied(self):
        """Test handling of permission errors"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("terra_mcp.server.fapi.list_entity_types", return_value=mock_response):
            # Access the underlying function from the FunctionTool wrapper
            get_workspace_data_tables_fn = mcp._tool_manager._tools["get_workspace_data_tables"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_workspace_data_tables_fn(
                    workspace_namespace="restricted",
                    workspace_name="workspace",
                    ctx=ctx,
                )

            assert "Access denied" in str(exc_info.value)


class TestGetSubmissionStatus:
    """Test get_submission_status tool"""

    @pytest.mark.asyncio
    async def test_get_submission_status_success(self):
        """Test successful submission status retrieval with inputResolutions omitted by default"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "submissionId": "abc-123",
            "status": "Succeeded",
            "submissionDate": "2024-01-01T10:00:00Z",
            "workflows": [
                {
                    "workflowId": "wf-1",
                    "status": "Succeeded",
                    "inputResolutions": [
                        {"inputName": "test.input1", "value": "gs://bucket/file1.txt"}
                    ],
                },
                {
                    "workflowId": "wf-2",
                    "status": "Succeeded",
                    "inputResolutions": [
                        {"inputName": "test.input2", "value": "gs://bucket/file2.txt"}
                    ],
                },
                {
                    "workflowId": "wf-3",
                    "status": "Failed",
                    "inputResolutions": [
                        {"inputName": "test.input3", "value": "gs://bucket/file3.txt"}
                    ],
                },
            ],
        }

        with patch("terra_mcp.server.fapi.get_submission", return_value=mock_response):
            # Access the underlying function from the FunctionTool wrapper
            get_submission_status_fn = mcp._tool_manager._tools["get_submission_status"].fn

            ctx = MagicMock()
            result = await get_submission_status_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="abc-123",
                ctx=ctx,
            )

            assert result["submission_id"] == "abc-123"
            assert result["status"] == "Succeeded"
            assert result["workflow_count"] == 3
            assert result["status_summary"]["Succeeded"] == 2
            assert result["status_summary"]["Failed"] == 1
            assert len(result["workflows"]) == 3

            # Verify inputResolutions is omitted by default
            for workflow in result["workflows"]:
                assert "inputResolutions" not in workflow
                assert "workflowId" in workflow  # Other fields still present
                assert "status" in workflow

    @pytest.mark.asyncio
    async def test_get_submission_status_with_many_workflows(self):
        """Test that workflow list is limited to 10"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "submissionId": "abc-123",
            "status": "Running",
            "submissionDate": "2024-01-01T10:00:00Z",
            "workflows": [{"workflowId": f"wf-{i}", "status": "Running"} for i in range(25)],
        }

        with patch("terra_mcp.server.fapi.get_submission", return_value=mock_response):
            # Access the underlying function from the FunctionTool wrapper
            get_submission_status_fn = mcp._tool_manager._tools["get_submission_status"].fn

            ctx = MagicMock()
            result = await get_submission_status_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="abc-123",
                ctx=ctx,
            )

            # Should return first 10 workflows only
            assert result["workflow_count"] == 25
            assert len(result["workflows"]) == 10
            assert result["note"] is not None
            assert "first 10 of 25" in result["note"]

    @pytest.mark.asyncio
    async def test_get_submission_status_not_found(self):
        """Test handling of non-existent submission"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.get_submission", return_value=mock_response):
            # Access the underlying function from the FunctionTool wrapper
            get_submission_status_fn = mcp._tool_manager._tools["get_submission_status"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_submission_status_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="nonexistent",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg
            assert "nonexistent" in error_msg
            assert "test-ns/test-ws" in error_msg

    @pytest.mark.asyncio
    async def test_get_submission_status_custom_workflow_limit(self):
        """Test that max_workflows parameter controls workflow list size"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "submissionId": "abc-123",
            "status": "Running",
            "submissionDate": "2024-01-01T10:00:00Z",
            "workflows": [{"workflowId": f"wf-{i}", "status": "Running"} for i in range(25)],
        }

        with patch("terra_mcp.server.fapi.get_submission", return_value=mock_response):
            get_submission_status_fn = mcp._tool_manager._tools["get_submission_status"].fn

            ctx = MagicMock()

            # Test with max_workflows=5
            result = await get_submission_status_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="abc-123",
                ctx=ctx,
                max_workflows=5,
            )

            assert result["workflow_count"] == 25
            assert len(result["workflows"]) == 5
            assert "first 5 of 25" in result["note"]

            # Test with max_workflows=0 (return all)
            result_all = await get_submission_status_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="abc-123",
                ctx=ctx,
                max_workflows=0,
            )

            assert result_all["workflow_count"] == 25
            assert len(result_all["workflows"]) == 25
            assert result_all["note"] is None

    @pytest.mark.asyncio
    async def test_get_submission_status_with_inputs(self):
        """Test that include_inputs=True preserves inputResolutions"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "submissionId": "abc-123",
            "status": "Succeeded",
            "submissionDate": "2024-01-01T10:00:00Z",
            "workflows": [
                {
                    "workflowId": "wf-1",
                    "status": "Succeeded",
                    "inputResolutions": [
                        {"inputName": "test.input1", "value": "gs://bucket/file1.txt"}
                    ],
                },
                {
                    "workflowId": "wf-2",
                    "status": "Failed",
                    "inputResolutions": [
                        {"inputName": "test.input2", "value": "gs://bucket/file2.txt"}
                    ],
                },
            ],
        }

        with patch("terra_mcp.server.fapi.get_submission", return_value=mock_response):
            get_submission_status_fn = mcp._tool_manager._tools["get_submission_status"].fn

            ctx = MagicMock()
            result = await get_submission_status_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="abc-123",
                ctx=ctx,
                include_inputs=True,
            )

            assert result["submission_id"] == "abc-123"
            assert result["workflow_count"] == 2
            assert len(result["workflows"]) == 2

            # Verify inputResolutions is INCLUDED when include_inputs=True
            for workflow in result["workflows"]:
                assert "inputResolutions" in workflow
                assert len(workflow["inputResolutions"]) == 1
                assert "inputName" in workflow["inputResolutions"][0]
                assert "value" in workflow["inputResolutions"][0]


class TestGetJobMetadata:
    """Test get_job_metadata tool with summary/query/full_download modes"""

    @pytest.mark.asyncio
    async def test_summary_mode_default(self):
        """Test summary mode (default) returns structured summary"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "wf-456",
            "workflowName": "test_workflow",
            "status": "Succeeded",
            "start": "2024-01-01T10:00:00Z",
            "end": "2024-01-01T11:00:00Z",
            "calls": {
                "task1": [{"executionStatus": "Succeeded"}],
                "task2": [{"executionStatus": "Succeeded"}],
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            result = await get_job_metadata_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
                # mode="summary" is default
            )

            # Verify structured summary format
            assert result["workflow_id"] == "wf-456"
            assert result["workflow_name"] == "test_workflow"
            assert result["status"] == "Succeeded"
            assert result["tasks"]["total"] == 2
            assert result["tasks"]["by_status"]["Succeeded"] == 2
            assert result["execution_summary"]["start"] == "2024-01-01T10:00:00Z"
            assert result["execution_summary"]["end"] == "2024-01-01T11:00:00Z"
            # Should not have failed_tasks since all succeeded
            assert "failed_tasks" not in result

    @pytest.mark.asyncio
    async def test_summary_mode_with_failures(self):
        """Test summary mode includes failed task details"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "wf-456",
            "workflowName": "test_workflow",
            "status": "Failed",
            "start": "2024-01-01T10:00:00Z",
            "end": "2024-01-01T11:00:00Z",
            "calls": {
                "task1": [{"executionStatus": "Succeeded"}],
                "task2": [
                    {
                        "executionStatus": "Failed",
                        "shardIndex": -1,
                        "attempt": 1,
                        "stderr": "gs://bucket/logs/stderr.log",
                        "stdout": "gs://bucket/logs/stdout.log",
                        "failures": [{"message": "OutOfMemoryError: Java heap space"}],
                        "start": "2024-01-01T10:30:00Z",
                        "end": "2024-01-01T10:45:00Z",
                    }
                ],
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            result = await get_job_metadata_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
                mode="summary",
            )

            # Verify failed tasks are included
            assert result["status"] == "Failed"
            assert result["tasks"]["total"] == 2
            assert result["tasks"]["by_status"]["Succeeded"] == 1
            assert result["tasks"]["by_status"]["Failed"] == 1
            assert "failed_tasks" in result
            assert len(result["failed_tasks"]) == 1

            failed_task = result["failed_tasks"][0]
            assert failed_task["name"] == "task2"
            assert failed_task["error"] == "OutOfMemoryError: Java heap space"
            assert failed_task["stderr_url"] == "gs://bucket/logs/stderr.log"
            assert failed_task["attempt"] == 1

    @pytest.mark.asyncio
    async def test_extract_mode_specific_output(self):
        """Test extract mode with task_name and output_name"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "wf-456",
            "workflowName": "test_workflow",
            "status": "Succeeded",
            "calls": {
                "illumina_demux": [
                    {
                        "shardIndex": -1,
                        "outputs": {
                            "commonBarcodes": "gs://bucket/barcodes.txt",
                            "metrics": "gs://bucket/metrics.txt",
                        },
                    }
                ],
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            result = await get_job_metadata_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
                mode="extract",
                task_name="illumina_demux",
                output_name="commonBarcodes",
            )

            assert result["mode"] == "extract"
            assert result["extracted_data"] == "gs://bucket/barcodes.txt"
            assert "commonBarcodes" in result["path_used"]
            assert result["size_chars"] > 0

    @pytest.mark.asyncio
    async def test_extract_mode_with_shard_index(self):
        """Test extract mode with shard_index parameter"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "wf-456",
            "workflowName": "test_workflow",
            "status": "Succeeded",
            "calls": {
                "scatter_task": [
                    {"shardIndex": 0, "outputs": {"result": "result_0"}},
                    {"shardIndex": 1, "outputs": {"result": "result_1"}},
                    {"shardIndex": 2, "outputs": {"result": "result_2"}},
                ],
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            result = await get_job_metadata_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
                mode="extract",
                task_name="scatter_task",
                shard_index=1,
                output_name="result",
            )

            assert result["mode"] == "extract"
            assert result["extracted_data"] == "result_1"

    @pytest.mark.asyncio
    async def test_extract_mode_field_path_wildcard(self):
        """Test extract mode with field_path using wildcards"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "wf-456",
            "workflowName": "test_workflow",
            "status": "Succeeded",
            "calls": {
                "task1": [{"executionStatus": "Succeeded", "runtimeAttributes": {"cpu": 2, "memory": "4GB"}}],
                "task2": [{"executionStatus": "Succeeded", "runtimeAttributes": {"cpu": 4, "memory": "8GB"}}],
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            result = await get_job_metadata_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
                mode="extract",
                field_path="calls.*[0].runtimeAttributes",
            )

            assert result["mode"] == "extract"
            assert "task1" in result["extracted_data"]
            assert "task2" in result["extracted_data"]
            assert result["extracted_data"]["task1"]["cpu"] == 2
            assert result["extracted_data"]["task2"]["cpu"] == 4

    @pytest.mark.asyncio
    async def test_extract_mode_missing_output(self):
        """Test extract mode fails gracefully when output not found"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "wf-456",
            "calls": {
                "task1": [{"outputs": {"file1": "gs://bucket/file1.txt"}}],
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            with pytest.raises(ToolError, match="Output 'missing_output' not found"):
                await get_job_metadata_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="sub-123",
                    workflow_id="wf-456",
                    ctx=ctx,
                    mode="extract",
                    task_name="task1",
                    output_name="missing_output",
                )

    @pytest.mark.asyncio
    async def test_extract_mode_missing_parameters(self):
        """Test extract mode requires either output_name or field_path"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "wf-456", "calls": {}}

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            with pytest.raises(ToolError, match='mode="extract" requires either output_name'):
                await get_job_metadata_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="sub-123",
                    workflow_id="wf-456",
                    ctx=ctx,
                    mode="extract",
                    # Missing both output_name and field_path
                )

    @pytest.mark.asyncio
    async def test_full_download_mode(self):
        """Test full_download mode returns complete metadata with warnings"""
        mock_metadata = {
            "id": "wf-456",
            "workflowName": "test_workflow",
            "status": "Succeeded",
            "calls": {f"task{i}": [{"executionStatus": "Succeeded"}] for i in range(50)},
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_metadata

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            result = await get_job_metadata_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
                mode="full_download",
            )

            # Verify response structure
            assert result["mode"] == "full_download"
            assert "size_warning" in result
            assert "size_chars" in result
            assert "estimated_tokens" in result
            assert result["metadata"] == mock_metadata

            # Verify warning contains helpful guidance
            assert "Write('/tmp/workflow_metadata.json'" in result["size_warning"]
            assert "jq" in result["size_warning"]



class TestGetWorkflowLogs:
    """Test get_workflow_logs tool"""

    @pytest.mark.asyncio
    async def test_get_workflow_logs_success(self):
        """Test successful workflow logs retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workflowName": "test_workflow",
            "status": "Failed",
            "calls": {
                "task1": [
                    {
                        "stderr": "gs://bucket/logs/task1-stderr.log",
                        "stdout": "gs://bucket/logs/task1-stdout.log",
                        "executionStatus": "Failed",
                        "attempt": 1,
                        "shardIndex": -1,
                    }
                ],
                "task2": [
                    {
                        "stderr": "gs://bucket/logs/task2-stderr.log",
                        "stdout": "gs://bucket/logs/task2-stdout.log",
                        "executionStatus": "Succeeded",
                        "attempt": 1,
                        "shardIndex": 0,
                    }
                ],
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response):
            get_workflow_logs_fn = mcp._tool_manager._tools["get_workflow_logs"].fn

            ctx = MagicMock()
            result = await get_workflow_logs_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
            )

            assert result["workflow_id"] == "wf-456"
            assert result["workflow_name"] == "test_workflow"
            assert result["status"] == "Failed"
            assert result["task_count"] == 2
            assert "task1" in result["logs"]
            assert "task2" in result["logs"]
            assert result["logs"]["task1"]["stderr_url"] == "gs://bucket/logs/task1-stderr.log"
            assert result["logs"]["task1"]["status"] == "Failed"
            assert result["logs"]["task2"]["status"] == "Succeeded"
            assert result["fetch_content"] is False

    @pytest.mark.asyncio
    async def test_get_workflow_logs_with_content_fetching(self):
        """Test workflow logs with actual content fetching from GCS"""
        from unittest.mock import Mock

        mock_metadata_response = MagicMock()
        mock_metadata_response.status_code = 200
        mock_metadata_response.json.return_value = {
            "workflowName": "test_workflow",
            "status": "Failed",
            "calls": {
                "task1": [
                    {
                        "stderr": "gs://bucket/logs/task1-stderr.log",
                        "stdout": "gs://bucket/logs/task1-stdout.log",
                        "executionStatus": "Failed",
                        "attempt": 1,
                        "shardIndex": -1,
                    }
                ],
            },
        }

        # Mock GCS client
        mock_blob = Mock()
        mock_blob.download_as_text.return_value = "Error: Task failed\nStacktrace here..."
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_storage_client = Mock()
        mock_storage_client.bucket.return_value = mock_bucket

        with patch(
            "terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_metadata_response
        ):
            with patch("terra_mcp.server.storage.Client", return_value=mock_storage_client):
                get_workflow_logs_fn = mcp._tool_manager._tools["get_workflow_logs"].fn

                ctx = MagicMock()
                result = await get_workflow_logs_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="sub-123",
                    workflow_id="wf-456",
                    ctx=ctx,
                    fetch_content=True,
                    truncate=False,
                )

                # Verify content was fetched
                assert result["fetch_content"] is True
                assert "stderr" in result["logs"]["task1"]
                assert "stdout" in result["logs"]["task1"]
                assert result["logs"]["task1"]["stderr"] == "Error: Task failed\nStacktrace here..."
                assert "stderr_truncated" not in result["logs"]["task1"]  # No truncation

    @pytest.mark.asyncio
    async def test_get_workflow_logs_with_truncation(self):
        """Test workflow logs with truncation applied"""
        from unittest.mock import Mock

        mock_metadata_response = MagicMock()
        mock_metadata_response.status_code = 200
        mock_metadata_response.json.return_value = {
            "workflowName": "test_workflow",
            "status": "Failed",
            "calls": {
                "task1": [
                    {
                        "stderr": "gs://bucket/logs/task1-stderr.log",
                        "stdout": "",
                        "executionStatus": "Failed",
                        "attempt": 1,
                        "shardIndex": -1,
                    }
                ],
            },
        }

        # Create a large log file that will be truncated
        large_log = "A" * 30000  # 30K characters

        mock_blob = Mock()
        mock_blob.download_as_text.return_value = large_log
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_storage_client = Mock()
        mock_storage_client.bucket.return_value = mock_bucket

        with patch(
            "terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_metadata_response
        ):
            with patch("terra_mcp.server.storage.Client", return_value=mock_storage_client):
                get_workflow_logs_fn = mcp._tool_manager._tools["get_workflow_logs"].fn

                ctx = MagicMock()
                result = await get_workflow_logs_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="sub-123",
                    workflow_id="wf-456",
                    ctx=ctx,
                    fetch_content=True,
                    truncate=True,
                    max_chars=10000,
                )

                # Verify truncation occurred
                assert result["logs"]["task1"]["stderr_truncated"] is True
                stderr_content = result["logs"]["task1"]["stderr"]
                assert len(stderr_content) < len(large_log)
                assert "Truncated" in stderr_content
                assert "Total log size: 30,000" in stderr_content

    @pytest.mark.asyncio
    async def test_get_workflow_logs_uses_exclude_key_not_include_key(self):
        """Test that get_workflow_logs uses exclude_key to avoid empty calls dict

        Regression test for bug where using include_key returned empty calls dict.
        FISS API's include_key parameter doesn't work as expected - it filters out
        nested data within the included keys, so we use exclude_key instead.
        """
        mock_metadata_response = MagicMock()
        mock_metadata_response.status_code = 200
        mock_metadata_response.json.return_value = {
            "workflowName": "test_workflow",
            "status": "Failed",
            "calls": {
                "task1": [
                    {
                        "stderr": "gs://bucket/stderr.log",
                        "stdout": "gs://bucket/stdout.log",
                        "executionStatus": "Failed",
                        "attempt": 1,
                        "shardIndex": 0,
                    }
                ],
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_metadata") as mock_get_metadata:
            mock_get_metadata.return_value = mock_metadata_response

            get_workflow_logs_fn = mcp._tool_manager._tools["get_workflow_logs"].fn

            ctx = MagicMock()
            result = await get_workflow_logs_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
                fetch_content=False,
            )

            # Verify that exclude_key was used (not include_key)
            mock_get_metadata.assert_called_once()
            call_kwargs = mock_get_metadata.call_args[1]
            assert "exclude_key" in call_kwargs
            assert "include_key" not in call_kwargs

            # Verify that logs were properly extracted (would be empty if include_key was used)
            assert result["task_count"] == 1
            assert "task1" in result["logs"]
            assert result["logs"]["task1"]["stderr_url"] == "gs://bucket/stderr.log"


class TestListSubmissions:
    """Test list_submissions tool"""

    @pytest.mark.asyncio
    async def test_list_submissions_success(self):
        """Test successful submission listing with sorting by date"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "submissionId": "sub-123",
                "status": "Succeeded",
                "submissionDate": "2024-01-01T10:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "MyWorkflow",
                "workflows": [{"workflowId": "wf-1", "status": "Succeeded"}],
            },
            {
                "submissionId": "sub-456",
                "status": "Running",
                "submissionDate": "2024-01-02T14:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "AnotherWorkflow",
                "workflows": [
                    {"workflowId": "wf-2", "status": "Running"},
                    {"workflowId": "wf-3", "status": "Succeeded"},
                ],
            },
        ]

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
            )

            assert len(result) == 2
            # Should be sorted by date descending (most recent first)
            assert result[0]["submissionId"] == "sub-456"  # 2024-01-02 (more recent)
            assert result[0]["status"] == "Running"
            assert result[1]["submissionId"] == "sub-123"  # 2024-01-01 (older)
            assert result[1]["status"] == "Succeeded"
            assert len(result[0]["workflows"]) == 2

    @pytest.mark.asyncio
    async def test_list_submissions_workspace_not_found(self):
        """Test handling of non-existent workspace"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await list_submissions_fn(
                    workspace_namespace="nonexistent",
                    workspace_name="workspace",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg
            assert "nonexistent/workspace" in error_msg

    @pytest.mark.asyncio
    async def test_list_submissions_access_denied(self):
        """Test handling of permission errors"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await list_submissions_fn(
                    workspace_namespace="restricted",
                    workspace_name="workspace",
                    ctx=ctx,
                )

            assert "Access denied" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_submissions_empty_workspace(self):
        """Test workspace with no submissions"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="empty-ws",
                ctx=ctx,
            )

            assert result == []
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_submissions_pagination_default(self):
        """Test pagination with default limit (20 submissions)"""
        # Create 25 mock submissions to test default pagination
        mock_submissions = []
        for i in range(25):
            mock_submissions.append(
                {
                    "submissionId": f"sub-{i:03d}",
                    "status": "Succeeded",
                    "submissionDate": f"2024-01-{i + 1:02d}T10:00:00Z",
                    "submitter": "user@example.com",
                    "methodConfigurationName": "MyWorkflow",
                    "workflows": [{"workflowId": f"wf-{i}", "status": "Succeeded"}],
                }
            )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_submissions

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
            )

            # Should return only 20 submissions (default limit)
            assert len(result) == 20
            # Should be sorted by date descending (most recent first)
            # Most recent is sub-024 (2024-01-25)
            assert result[0]["submissionId"] == "sub-024"
            assert result[19]["submissionId"] == "sub-005"

    @pytest.mark.asyncio
    async def test_list_submissions_pagination_custom_limit(self):
        """Test pagination with custom limit"""
        # Create 15 mock submissions
        mock_submissions = []
        for i in range(15):
            mock_submissions.append(
                {
                    "submissionId": f"sub-{i:03d}",
                    "status": "Succeeded",
                    "submissionDate": f"2024-01-{i + 1:02d}T10:00:00Z",
                    "submitter": "user@example.com",
                    "methodConfigurationName": "MyWorkflow",
                    "workflows": [],
                }
            )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_submissions

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
                limit=5,
            )

            # Should return only 5 submissions
            assert len(result) == 5
            # Should be most recent 5
            assert result[0]["submissionId"] == "sub-014"
            assert result[4]["submissionId"] == "sub-010"

    @pytest.mark.asyncio
    async def test_list_submissions_filter_by_status(self):
        """Test filtering by submission status"""
        mock_submissions = [
            {
                "submissionId": "sub-001",
                "status": "Succeeded",
                "submissionDate": "2024-01-01T10:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "MyWorkflow",
                "workflows": [],
            },
            {
                "submissionId": "sub-002",
                "status": "Failed",
                "submissionDate": "2024-01-02T10:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "MyWorkflow",
                "workflows": [],
            },
            {
                "submissionId": "sub-003",
                "status": "Running",
                "submissionDate": "2024-01-03T10:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "MyWorkflow",
                "workflows": [],
            },
            {
                "submissionId": "sub-004",
                "status": "Failed",
                "submissionDate": "2024-01-04T10:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "MyWorkflow",
                "workflows": [],
            },
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_submissions

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
                status="Failed",
            )

            # Should return only Failed submissions
            assert len(result) == 2
            assert all(s["status"] == "Failed" for s in result)
            # Should be sorted by date descending
            assert result[0]["submissionId"] == "sub-004"
            assert result[1]["submissionId"] == "sub-002"

    @pytest.mark.asyncio
    async def test_list_submissions_filter_by_submitter(self):
        """Test filtering by submitter email"""
        mock_submissions = [
            {
                "submissionId": "sub-001",
                "status": "Succeeded",
                "submissionDate": "2024-01-01T10:00:00Z",
                "submitter": "alice@example.com",
                "methodConfigurationName": "MyWorkflow",
                "workflows": [],
            },
            {
                "submissionId": "sub-002",
                "status": "Succeeded",
                "submissionDate": "2024-01-02T10:00:00Z",
                "submitter": "bob@example.com",
                "methodConfigurationName": "MyWorkflow",
                "workflows": [],
            },
            {
                "submissionId": "sub-003",
                "status": "Running",
                "submissionDate": "2024-01-03T10:00:00Z",
                "submitter": "alice@example.com",
                "methodConfigurationName": "MyWorkflow",
                "workflows": [],
            },
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_submissions

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
                submitter="alice@example.com",
            )

            # Should return only alice's submissions
            assert len(result) == 2
            assert all(s["submitter"] == "alice@example.com" for s in result)
            # Should be sorted by date descending
            assert result[0]["submissionId"] == "sub-003"
            assert result[1]["submissionId"] == "sub-001"

    @pytest.mark.asyncio
    async def test_list_submissions_filter_by_workflow_name(self):
        """Test filtering by workflow/method configuration name"""
        mock_submissions = [
            {
                "submissionId": "sub-001",
                "status": "Succeeded",
                "submissionDate": "2024-01-01T10:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "AlignmentWorkflow",
                "workflows": [],
            },
            {
                "submissionId": "sub-002",
                "status": "Succeeded",
                "submissionDate": "2024-01-02T10:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "VariantCalling",
                "workflows": [],
            },
            {
                "submissionId": "sub-003",
                "status": "Running",
                "submissionDate": "2024-01-03T10:00:00Z",
                "submitter": "user@example.com",
                "methodConfigurationName": "AlignmentWorkflow",
                "workflows": [],
            },
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_submissions

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
                workflow_name="AlignmentWorkflow",
            )

            # Should return only AlignmentWorkflow submissions
            assert len(result) == 2
            assert all(s["methodConfigurationName"] == "AlignmentWorkflow" for s in result)
            # Should be sorted by date descending
            assert result[0]["submissionId"] == "sub-003"
            assert result[1]["submissionId"] == "sub-001"

    @pytest.mark.asyncio
    async def test_list_submissions_combined_filters(self):
        """Test combining multiple filters"""
        mock_submissions = []
        for i in range(10):
            mock_submissions.append(
                {
                    "submissionId": f"sub-{i:03d}",
                    "status": "Failed" if i % 3 == 0 else "Succeeded",
                    "submissionDate": f"2024-01-{i + 1:02d}T10:00:00Z",
                    "submitter": "alice@example.com" if i % 2 == 0 else "bob@example.com",
                    "methodConfigurationName": "WorkflowA" if i < 5 else "WorkflowB",
                    "workflows": [],
                }
            )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_submissions

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
                status="Failed",
                submitter="alice@example.com",
                limit=5,
            )

            # Should return Failed submissions from alice only
            # Matching indices: 0 (Failed, alice), 6 (Failed, alice)
            assert len(result) == 2
            assert all(s["status"] == "Failed" for s in result)
            assert all(s["submitter"] == "alice@example.com" for s in result)
            # Should be sorted by date descending
            assert result[0]["submissionId"] == "sub-006"
            assert result[1]["submissionId"] == "sub-000"

    @pytest.mark.asyncio
    async def test_list_submissions_limit_none_returns_all(self):
        """Test that limit=None returns all filtered submissions"""
        mock_submissions = []
        for i in range(25):
            mock_submissions.append(
                {
                    "submissionId": f"sub-{i:03d}",
                    "status": "Succeeded",
                    "submissionDate": f"2024-01-{i + 1:02d}T10:00:00Z",
                    "submitter": "user@example.com",
                    "methodConfigurationName": "MyWorkflow",
                    "workflows": [],
                }
            )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_submissions

        with patch("terra_mcp.server.fapi.list_submissions", return_value=mock_response):
            list_submissions_fn = mcp._tool_manager._tools["list_submissions"].fn

            ctx = MagicMock()
            result = await list_submissions_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                ctx=ctx,
                limit=None,
            )

            # Should return all 25 submissions
            assert len(result) == 25
            # Should still be sorted by date descending
            assert result[0]["submissionId"] == "sub-024"
            assert result[24]["submissionId"] == "sub-000"


class TestGetWorkflowOutputs:
    """Test get_workflow_outputs tool"""

    @pytest.mark.asyncio
    async def test_get_workflow_outputs_success(self):
        """Test successful workflow outputs retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "wf-123",
            "outputs": {
                "MyWorkflow.output_file": "gs://bucket/outputs/result.bam",
                "MyWorkflow.output_index": "gs://bucket/outputs/result.bam.bai",
                "MyWorkflow.metrics": {"quality_score": 95.5, "read_count": 1000000},
            },
        }

        with patch("terra_mcp.server.fapi.get_workflow_outputs", return_value=mock_response):
            get_workflow_outputs_fn = mcp._tool_manager._tools["get_workflow_outputs"].fn

            ctx = MagicMock()
            result = await get_workflow_outputs_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-123",
                ctx=ctx,
            )

            assert result["id"] == "wf-123"
            assert "outputs" in result
            assert "MyWorkflow.output_file" in result["outputs"]
            assert result["outputs"]["MyWorkflow.output_file"] == "gs://bucket/outputs/result.bam"

    @pytest.mark.asyncio
    async def test_get_workflow_outputs_not_found(self):
        """Test handling of non-existent workflow"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.get_workflow_outputs", return_value=mock_response):
            get_workflow_outputs_fn = mcp._tool_manager._tools["get_workflow_outputs"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_workflow_outputs_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="sub-123",
                    workflow_id="nonexistent",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg
            assert "nonexistent" in error_msg

    @pytest.mark.asyncio
    async def test_get_workflow_outputs_access_denied(self):
        """Test handling of permission errors"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("terra_mcp.server.fapi.get_workflow_outputs", return_value=mock_response):
            get_workflow_outputs_fn = mcp._tool_manager._tools["get_workflow_outputs"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_workflow_outputs_fn(
                    workspace_namespace="restricted",
                    workspace_name="workspace",
                    submission_id="sub-123",
                    workflow_id="wf-123",
                    ctx=ctx,
                )

            assert "Access denied" in str(exc_info.value)


class TestGetWorkflowCost:
    """Test get_workflow_cost tool"""

    @pytest.mark.asyncio
    async def test_get_workflow_cost_success(self):
        """Test successful workflow cost retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "cost": 2.45,
            "currency": "USD",
            "costBreakdown": {
                "compute": 2.00,
                "storage": 0.35,
                "network": 0.10,
            },
            "status": "complete",
        }

        with patch("terra_mcp.server.fapi.get_workflow_cost", return_value=mock_response):
            get_workflow_cost_fn = mcp._tool_manager._tools["get_workflow_cost"].fn

            ctx = MagicMock()
            result = await get_workflow_cost_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-123",
                ctx=ctx,
            )

            assert result["cost"] == 2.45
            assert result["currency"] == "USD"
            assert "costBreakdown" in result
            assert result["costBreakdown"]["compute"] == 2.00

    @pytest.mark.asyncio
    async def test_get_workflow_cost_pending(self):
        """Test workflow cost when calculation is still pending"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "cost": None,
            "currency": "USD",
            "status": "pending",
            "message": "Cost calculation in progress",
        }

        with patch("terra_mcp.server.fapi.get_workflow_cost", return_value=mock_response):
            get_workflow_cost_fn = mcp._tool_manager._tools["get_workflow_cost"].fn

            ctx = MagicMock()
            result = await get_workflow_cost_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-123",
                ctx=ctx,
            )

            assert result["status"] == "pending"
            assert result["cost"] is None

    @pytest.mark.asyncio
    async def test_get_workflow_cost_not_found(self):
        """Test handling of non-existent workflow"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.get_workflow_cost", return_value=mock_response):
            get_workflow_cost_fn = mcp._tool_manager._tools["get_workflow_cost"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_workflow_cost_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="sub-123",
                    workflow_id="nonexistent",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg
            assert "nonexistent" in error_msg

    @pytest.mark.asyncio
    async def test_get_workflow_cost_access_denied(self):
        """Test handling of permission errors"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("terra_mcp.server.fapi.get_workflow_cost", return_value=mock_response):
            get_workflow_cost_fn = mcp._tool_manager._tools["get_workflow_cost"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_workflow_cost_fn(
                    workspace_namespace="restricted",
                    workspace_name="workspace",
                    submission_id="sub-123",
                    workflow_id="wf-123",
                    ctx=ctx,
                )

            assert "Access denied" in str(exc_info.value)


class TestTruncationHelper:
    """Test truncation helper function"""

    def test_truncate_short_content(self):
        """Test that short content is not truncated"""
        from terra_mcp.server import _truncate_log_content

        content = "Short log content"
        result, was_truncated = _truncate_log_content(content, max_chars=1000)

        assert result == content
        assert was_truncated is False

    def test_truncate_long_content(self):
        """Test that long content is truncated correctly"""
        from terra_mcp.server import _truncate_log_content

        # Create content with identifiable head and tail
        head = "START" * 1000  # 5000 chars
        middle = "MIDDLE" * 5000  # 30000 chars
        tail = "END" * 1000  # 3000 chars
        content = head + middle + tail

        result, was_truncated = _truncate_log_content(content, max_chars=10000)

        assert was_truncated is True
        assert "START" in result  # Head preserved
        assert "END" in result  # Tail preserved
        assert "Truncated" in result  # Truncation message present
        assert len(result) <= 10100  # Approximately max_chars (with message)

    def test_truncate_custom_max_chars(self):
        """Test truncation with custom max_chars"""
        from terra_mcp.server import _truncate_log_content

        content = "X" * 100000
        result, was_truncated = _truncate_log_content(content, max_chars=5000)

        assert was_truncated is True
        assert len(result) <= 5100  # Approximately 5000 + message


class TestGCSLogFetching:
    """Test GCS log fetching helper"""

    def test_fetch_gcs_log_invalid_url(self):
        """Test handling of invalid GCS URLs"""
        from terra_mcp.server import _fetch_gcs_log

        ctx = MagicMock()

        # Test non-GCS URL
        result = _fetch_gcs_log("http://example.com/log.txt", ctx)
        assert result is None

        # Test malformed GCS URL
        result = _fetch_gcs_log("gs://bucket-only", ctx)
        assert result is None

    def test_fetch_gcs_log_success(self):
        """Test successful GCS log fetch"""
        from unittest.mock import Mock

        from terra_mcp.server import _fetch_gcs_log

        mock_blob = Mock()
        mock_blob.download_as_text.return_value = "Log content here"
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket

        ctx = MagicMock()

        with patch("terra_mcp.server.storage.Client", return_value=mock_client):
            result = _fetch_gcs_log("gs://my-bucket/path/to/log.txt", ctx)

            assert result == "Log content here"
            mock_client.bucket.assert_called_once_with("my-bucket")
            mock_bucket.blob.assert_called_once_with("path/to/log.txt")

    def test_fetch_gcs_log_exception(self):
        """Test handling of GCS fetch exceptions"""
        from unittest.mock import Mock

        from terra_mcp.server import _fetch_gcs_log

        mock_client = Mock()
        mock_client.bucket.side_effect = Exception("GCS error")

        ctx = MagicMock()

        with patch("terra_mcp.server.storage.Client", return_value=mock_client):
            result = _fetch_gcs_log("gs://my-bucket/path/to/log.txt", ctx)

            assert result is None
            # Verify error was logged
            ctx.error.assert_called()


# ===== Phase 3: Workflow Management Tools Tests =====


class TestGetEntities:
    """Test get_entities tool"""

    @pytest.mark.asyncio
    async def test_get_entities_success(self):
        """Test successful entity retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "name": "sample_1",
                "entityType": "sample",
                "attributes": {
                    "sample_id": "S001",
                    "participant": "P001",
                    "tissue_type": "blood",
                },
            },
            {
                "name": "sample_2",
                "entityType": "sample",
                "attributes": {
                    "sample_id": "S002",
                    "participant": "P002",
                    "tissue_type": "tumor",
                },
            },
        ]

        with patch("terra_mcp.server.fapi.get_entities", return_value=mock_response):
            get_entities_fn = mcp._tool_manager._tools["get_entities"].fn

            ctx = MagicMock()
            result = await get_entities_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                entity_type="sample",
                ctx=ctx,
            )

            assert len(result["entities"]) == 2
            assert result["entity_type"] == "sample"
            assert result["count"] == 2
            assert result["entities"][0]["name"] == "sample_1"
            assert result["entities"][0]["attributes"]["sample_id"] == "S001"

    @pytest.mark.asyncio
    async def test_get_entities_workspace_not_found(self):
        """Test handling of non-existent workspace"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.get_entities", return_value=mock_response):
            get_entities_fn = mcp._tool_manager._tools["get_entities"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_entities_fn(
                    workspace_namespace="nonexistent",
                    workspace_name="workspace",
                    entity_type="sample",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg

    @pytest.mark.asyncio
    async def test_get_entities_empty_table(self):
        """Test workspace with no entities of given type"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch("terra_mcp.server.fapi.get_entities", return_value=mock_response):
            get_entities_fn = mcp._tool_manager._tools["get_entities"].fn

            ctx = MagicMock()
            result = await get_entities_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                entity_type="participant",
                ctx=ctx,
            )

            assert result["count"] == 0
            assert result["entities"] == []


class TestGetMethodConfig:
    """Test get_method_config tool"""

    @pytest.mark.asyncio
    async def test_get_method_config_success(self):
        """Test successful method config retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "namespace": "broad-dsde-methods",
            "name": "my_workflow",
            "rootEntityType": "sample",
            "methodRepoMethod": {
                "methodNamespace": "broad",
                "methodName": "MyWorkflow",
                "methodVersion": 5,
            },
            "inputs": {
                "MyWorkflow.input_bam": "this.bam_file",
                "MyWorkflow.reference": "workspace.reference_genome",
            },
            "outputs": {
                "MyWorkflow.output_vcf": "this.output_vcf",
            },
        }

        with patch("terra_mcp.server.fapi.get_workspace_config", return_value=mock_response):
            get_method_config_fn = mcp._tool_manager._tools["get_method_config"].fn

            ctx = MagicMock()
            result = await get_method_config_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                config_namespace="broad-dsde-methods",
                config_name="my_workflow",
                ctx=ctx,
            )

            assert result["name"] == "my_workflow"
            assert result["rootEntityType"] == "sample"
            assert result["methodRepoMethod"]["methodVersion"] == 5
            assert "MyWorkflow.input_bam" in result["inputs"]

    @pytest.mark.asyncio
    async def test_get_method_config_not_found(self):
        """Test handling of non-existent method config"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.get_workspace_config", return_value=mock_response):
            get_method_config_fn = mcp._tool_manager._tools["get_method_config"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_method_config_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    config_namespace="broad",
                    config_name="nonexistent",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg


class TestUpdateMethodConfig:
    """Test update_method_config tool"""

    @pytest.mark.asyncio
    async def test_update_method_config_success(self, enable_writes):
        """Test successful method config update"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "namespace": "broad-dsde-methods",
            "name": "my_workflow",
            "methodRepoMethod": {"methodVersion": 6},
        }

        update_body = {
            "methodRepoMethod": {
                "methodNamespace": "broad",
                "methodName": "MyWorkflow",
                "methodVersion": 6,
            }
        }

        with patch("terra_mcp.server.fapi.update_workspace_config", return_value=mock_response):
            update_method_config_fn = mcp._tool_manager._tools["update_method_config"].fn

            ctx = MagicMock()
            result = await update_method_config_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                config_namespace="broad-dsde-methods",
                config_name="my_workflow",
                updates=update_body,
                ctx=ctx,
            )

            assert result["methodRepoMethod"]["methodVersion"] == 6

    @pytest.mark.asyncio
    async def test_update_method_config_not_found(self, enable_writes):
        """Test handling of non-existent method config"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.update_workspace_config", return_value=mock_response):
            update_method_config_fn = mcp._tool_manager._tools["update_method_config"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await update_method_config_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    config_namespace="broad",
                    config_name="nonexistent",
                    updates={"methodRepoMethod": {"methodVersion": 6}},
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg


class TestCopyMethodConfig:
    """Test copy_method_config tool"""

    @pytest.mark.asyncio
    async def test_copy_method_config_success(self, enable_writes):
        """Test successful method config copy"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "namespace": "broad-dsde-methods",
            "name": "my_workflow_copy",
            "rootEntityType": "sample",
        }

        with patch("terra_mcp.server.fapi.copy_config_from_repo", return_value=mock_response):
            copy_method_config_fn = mcp._tool_manager._tools["copy_method_config"].fn

            ctx = MagicMock()
            result = await copy_method_config_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                from_config_namespace="broad-dsde-methods",
                from_config_name="my_workflow",
                to_config_namespace="broad-dsde-methods",
                to_config_name="my_workflow_copy",
                ctx=ctx,
            )

            assert result["name"] == "my_workflow_copy"

    @pytest.mark.asyncio
    async def test_copy_method_config_source_not_found(self, enable_writes):
        """Test handling of non-existent source config"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.copy_config_from_repo", return_value=mock_response):
            copy_method_config_fn = mcp._tool_manager._tools["copy_method_config"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await copy_method_config_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    from_config_namespace="broad",
                    from_config_name="nonexistent",
                    to_config_namespace="broad",
                    to_config_name="copy",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg or "Failed to copy" in error_msg


class TestSubmitWorkflow:
    """Test submit_workflow tool"""

    @pytest.mark.asyncio
    async def test_submit_workflow_success(self, enable_writes):
        """Test successful workflow submission"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "submissionId": "new-sub-123",
            "status": "Submitted",
            "submissionDate": "2024-01-01T10:00:00Z",
        }

        with patch("terra_mcp.server.fapi.create_submission", return_value=mock_response):
            submit_workflow_fn = mcp._tool_manager._tools["submit_workflow"].fn

            ctx = MagicMock()
            result = await submit_workflow_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                config_namespace="broad-dsde-methods",
                config_name="my_workflow",
                entity_type="sample",
                entity_name="sample_1",
                ctx=ctx,
            )

            assert result["submissionId"] == "new-sub-123"
            assert result["status"] == "Submitted"

    @pytest.mark.asyncio
    async def test_submit_workflow_config_not_found(self, enable_writes):
        """Test handling of non-existent method config"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.create_submission", return_value=mock_response):
            submit_workflow_fn = mcp._tool_manager._tools["submit_workflow"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await submit_workflow_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    config_namespace="broad",
                    config_name="nonexistent",
                    entity_type="sample",
                    entity_name="sample_1",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg or "Failed to submit" in error_msg

    @pytest.mark.asyncio
    async def test_submit_workflow_with_expression(self, enable_writes):
        """Test workflow submission with entity expression"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "submissionId": "new-sub-456",
            "status": "Submitted",
        }

        with patch("terra_mcp.server.fapi.create_submission", return_value=mock_response):
            submit_workflow_fn = mcp._tool_manager._tools["submit_workflow"].fn

            ctx = MagicMock()
            result = await submit_workflow_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                config_namespace="broad-dsde-methods",
                config_name="my_workflow",
                entity_type="sample_set",
                entity_name=None,
                expression="this.samples",
                ctx=ctx,
            )

            assert result["submissionId"] == "new-sub-456"


class TestAbortSubmission:
    """Test abort_submission tool"""

    @pytest.mark.asyncio
    async def test_abort_submission_success(self, enable_writes):
        """Test successful submission abort"""
        mock_response = MagicMock()
        mock_response.status_code = 204  # No content - successful abort

        with patch("terra_mcp.server.fapi.abort_submission", return_value=mock_response):
            abort_submission_fn = mcp._tool_manager._tools["abort_submission"].fn

            ctx = MagicMock()
            result = await abort_submission_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                ctx=ctx,
            )

            assert result["submission_id"] == "sub-123"
            assert result["status"] == "abort_requested"

    @pytest.mark.asyncio
    async def test_abort_submission_not_found(self, enable_writes):
        """Test handling of non-existent submission"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("terra_mcp.server.fapi.abort_submission", return_value=mock_response):
            abort_submission_fn = mcp._tool_manager._tools["abort_submission"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await abort_submission_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="nonexistent",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg

    @pytest.mark.asyncio
    async def test_abort_submission_already_completed(self, enable_writes):
        """Test aborting already completed submission"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Submission already completed"

        with patch("terra_mcp.server.fapi.abort_submission", return_value=mock_response):
            abort_submission_fn = mcp._tool_manager._tools["abort_submission"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await abort_submission_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="completed-sub",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "Failed to abort" in error_msg or "400" in error_msg


# ===== Phase 4: Data Management Tools Tests =====


class TestUploadEntities:
    """Test upload_entities tool"""

    @pytest.mark.asyncio
    async def test_upload_entities_success(self, enable_writes):
        """Test successful entity upload"""
        mock_response = MagicMock()
        mock_response.status_code = 200

        entity_data = [
            {
                "name": "sample_1",
                "entityType": "sample",
                "attributes": {
                    "sample_id": "S001",
                    "participant": "P001",
                    "tissue_type": "blood",
                },
            },
            {
                "name": "sample_2",
                "entityType": "sample",
                "attributes": {
                    "sample_id": "S002",
                    "participant": "P002",
                    "tissue_type": "tumor",
                },
            },
        ]

        with patch("terra_mcp.server.fapi.upload_entities", return_value=mock_response):
            upload_entities_fn = mcp._tool_manager._tools["upload_entities"].fn

            ctx = MagicMock()
            result = await upload_entities_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                entity_data=entity_data,
                ctx=ctx,
            )

            assert result["success"] is True
            assert result["entity_count"] == 2
            assert result["entity_type"] == "sample"

    @pytest.mark.asyncio
    async def test_upload_entities_workspace_not_found(self, enable_writes):
        """Test handling of non-existent workspace"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 404

        entity_data = [
            {
                "name": "sample_1",
                "entityType": "sample",
                "attributes": {"sample_id": "S001"},
            }
        ]

        with patch("terra_mcp.server.fapi.upload_entities", return_value=mock_response):
            upload_entities_fn = mcp._tool_manager._tools["upload_entities"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await upload_entities_fn(
                    workspace_namespace="nonexistent",
                    workspace_name="workspace",
                    entity_data=entity_data,
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg

    @pytest.mark.asyncio
    async def test_upload_entities_access_denied(self, enable_writes):
        """Test handling of permission errors"""
        from fastmcp.exceptions import ToolError

        mock_response = MagicMock()
        mock_response.status_code = 403

        entity_data = [
            {
                "name": "sample_1",
                "entityType": "sample",
                "attributes": {"sample_id": "S001"},
            }
        ]

        with patch("terra_mcp.server.fapi.upload_entities", return_value=mock_response):
            upload_entities_fn = mcp._tool_manager._tools["upload_entities"].fn

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await upload_entities_fn(
                    workspace_namespace="restricted",
                    workspace_name="workspace",
                    entity_data=entity_data,
                    ctx=ctx,
                )

            assert "Access denied" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_entities_empty_data(self, enable_writes):
        """Test handling of empty entity data"""
        from fastmcp.exceptions import ToolError

        upload_entities_fn = mcp._tool_manager._tools["upload_entities"].fn

        ctx = MagicMock()

        with pytest.raises(ToolError) as exc_info:
            await upload_entities_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                entity_data=[],
                ctx=ctx,
            )

        error_msg = str(exc_info.value)
        assert "cannot be empty" in error_msg

    @pytest.mark.asyncio
    async def test_upload_entities_invalid_format(self, enable_writes):
        """Test handling of invalid entity data format"""
        from fastmcp.exceptions import ToolError

        # Missing entityType
        invalid_data = [
            {
                "name": "sample_1",
                "attributes": {"sample_id": "S001"},
            }
        ]

        upload_entities_fn = mcp._tool_manager._tools["upload_entities"].fn

        ctx = MagicMock()

        with pytest.raises(ToolError) as exc_info:
            await upload_entities_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                entity_data=invalid_data,
                ctx=ctx,
            )

        error_msg = str(exc_info.value)
        assert "must have" in error_msg or "entityType" in error_msg


class TestReadOnlyMode:
    """Test read-only mode safety feature"""

    @pytest.mark.asyncio
    async def test_update_method_config_blocked_in_readonly_mode(self):
        """Test that update_method_config is blocked in read-only mode"""
        from fastmcp.exceptions import ToolError

        import terra_mcp.server as server_module

        # Save original value
        original_allow_writes = server_module.ALLOW_WRITES

        try:
            # Set read-only mode
            server_module.ALLOW_WRITES = False

            update_method_config_fn = mcp._tool_manager._tools["update_method_config"].fn
            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await update_method_config_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    config_namespace="config-ns",
                    config_name="config-name",
                    updates={"methodRepoMethod": {"methodVersion": 5}},
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "read-only mode" in error_msg
            assert "--allow-writes" in error_msg

        finally:
            # Restore original value
            server_module.ALLOW_WRITES = original_allow_writes

    @pytest.mark.asyncio
    async def test_copy_method_config_blocked_in_readonly_mode(self):
        """Test that copy_method_config is blocked in read-only mode"""
        from fastmcp.exceptions import ToolError

        import terra_mcp.server as server_module

        original_allow_writes = server_module.ALLOW_WRITES

        try:
            server_module.ALLOW_WRITES = False

            copy_method_config_fn = mcp._tool_manager._tools["copy_method_config"].fn
            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await copy_method_config_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    from_config_namespace="config-ns",
                    from_config_name="config-name",
                    to_config_namespace="new-ns",
                    to_config_name="new-name",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "read-only mode" in error_msg
            assert "--allow-writes" in error_msg

        finally:
            server_module.ALLOW_WRITES = original_allow_writes

    @pytest.mark.asyncio
    async def test_submit_workflow_blocked_in_readonly_mode(self):
        """Test that submit_workflow is blocked in read-only mode"""
        from fastmcp.exceptions import ToolError

        import terra_mcp.server as server_module

        original_allow_writes = server_module.ALLOW_WRITES

        try:
            server_module.ALLOW_WRITES = False

            submit_workflow_fn = mcp._tool_manager._tools["submit_workflow"].fn
            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await submit_workflow_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    config_namespace="config-ns",
                    config_name="config-name",
                    entity_type="sample",
                    entity_name="sample_1",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "read-only mode" in error_msg
            assert "--allow-writes" in error_msg

        finally:
            server_module.ALLOW_WRITES = original_allow_writes

    @pytest.mark.asyncio
    async def test_abort_submission_blocked_in_readonly_mode(self):
        """Test that abort_submission is blocked in read-only mode"""
        from fastmcp.exceptions import ToolError

        import terra_mcp.server as server_module

        original_allow_writes = server_module.ALLOW_WRITES

        try:
            server_module.ALLOW_WRITES = False

            abort_submission_fn = mcp._tool_manager._tools["abort_submission"].fn
            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await abort_submission_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="sub-123",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "read-only mode" in error_msg
            assert "--allow-writes" in error_msg

        finally:
            server_module.ALLOW_WRITES = original_allow_writes

    @pytest.mark.asyncio
    async def test_upload_entities_blocked_in_readonly_mode(self):
        """Test that upload_entities is blocked in read-only mode"""
        from fastmcp.exceptions import ToolError

        import terra_mcp.server as server_module

        original_allow_writes = server_module.ALLOW_WRITES

        try:
            server_module.ALLOW_WRITES = False

            upload_entities_fn = mcp._tool_manager._tools["upload_entities"].fn
            ctx = MagicMock()

            entity_data = [
                {
                    "name": "sample_1",
                    "entityType": "sample",
                    "attributes": {"sample_id": "S001"},
                }
            ]

            with pytest.raises(ToolError) as exc_info:
                await upload_entities_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    entity_data=entity_data,
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "read-only mode" in error_msg
            assert "--allow-writes" in error_msg

        finally:
            server_module.ALLOW_WRITES = original_allow_writes

    @pytest.mark.asyncio
    async def test_write_tools_allowed_when_writes_enabled(self):
        """Test that write tools work when ALLOW_WRITES is True"""
        import terra_mcp.server as server_module

        original_allow_writes = server_module.ALLOW_WRITES

        try:
            # Enable writes
            server_module.ALLOW_WRITES = True

            # Test update_method_config passes the write check
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "namespace": "config-ns",
                "name": "config-name",
                "methodRepoMethod": {"methodVersion": 5},
            }

            with patch("terra_mcp.server.fapi.update_workspace_config", return_value=mock_response):
                update_method_config_fn = mcp._tool_manager._tools["update_method_config"].fn
                ctx = MagicMock()

                result = await update_method_config_fn(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    config_namespace="config-ns",
                    config_name="config-name",
                    updates={"methodRepoMethod": {"methodVersion": 5}},
                    ctx=ctx,
                )

                # Should succeed without ToolError
                assert result["namespace"] == "config-ns"
                assert result["name"] == "config-name"

        finally:
            server_module.ALLOW_WRITES = original_allow_writes

    @pytest.mark.asyncio
    async def test_read_tools_always_work(self):
        """Test that read-only tools work regardless of ALLOW_WRITES setting"""
        import terra_mcp.server as server_module

        original_allow_writes = server_module.ALLOW_WRITES

        try:
            # Test with writes disabled
            server_module.ALLOW_WRITES = False

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = [
                {
                    "workspace": {
                        "namespace": "test-ns",
                        "name": "test-ws",
                        "createdBy": "user@example.com",
                        "createdDate": "2024-01-01T00:00:00Z",
                    }
                }
            ]

            with patch("terra_mcp.server.fapi.list_workspaces", return_value=mock_response):
                list_workspaces_fn = mcp._tool_manager._tools["list_workspaces"].fn
                ctx = MagicMock()

                result = await list_workspaces_fn(ctx)

                # Should succeed even with writes disabled
                assert len(result) == 1
                assert result[0]["namespace"] == "test-ns"

        finally:
            server_module.ALLOW_WRITES = original_allow_writes
