"""Tests for Terra.Bio MCP Server

Basic test suite to verify server initialization, tool registration,
and error handling with mocked FISS API calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from terra_mcp.server import mcp


class TestServerInitialization:
    """Test basic server setup and configuration"""

    def test_server_exists(self):
        """Verify MCP server instance exists"""
        assert mcp is not None
        assert mcp.name == "Terra.Bio MCP Server"

    def test_server_has_tools(self):
        """Verify all Phase 1 tools are registered"""
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
        """Test successful submission status retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "submissionId": "abc-123",
            "status": "Succeeded",
            "submissionDate": "2024-01-01T10:00:00Z",
            "workflows": [
                {"workflowId": "wf-1", "status": "Succeeded"},
                {"workflowId": "wf-2", "status": "Succeeded"},
                {"workflowId": "wf-3", "status": "Failed"},
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


class TestGetJobMetadata:
    """Test get_job_metadata tool"""

    @pytest.mark.asyncio
    async def test_get_job_metadata_success(self):
        """Test successful job metadata retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workflowName": "test_workflow",
            "status": "Succeeded",
            "start": "2024-01-01T10:00:00Z",
            "end": "2024-01-01T11:00:00Z",
            "calls": {},
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
            )

            assert result["workflowName"] == "test_workflow"
            assert result["status"] == "Succeeded"

    @pytest.mark.asyncio
    async def test_get_job_metadata_with_filtering(self):
        """Test job metadata with include_keys filtering"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "Failed",
            "failures": [{"message": "Task failed"}],
        }

        with patch(
            "terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_response
        ) as mock_call:
            get_job_metadata_fn = mcp._tool_manager._tools["get_job_metadata"].fn

            ctx = MagicMock()
            result = await get_job_metadata_fn(
                workspace_namespace="test-ns",
                workspace_name="test-ws",
                submission_id="sub-123",
                workflow_id="wf-456",
                ctx=ctx,
                include_keys=["status", "failures"],
            )

            # Verify the API was called with include_key parameter
            mock_call.assert_called_once()
            assert mock_call.call_args[1]["include_key"] == ["status", "failures"]

            assert result["status"] == "Failed"
            assert "failures" in result


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

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_metadata_response):
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

        with patch("terra_mcp.server.fapi.get_workflow_metadata", return_value=mock_metadata_response):
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
