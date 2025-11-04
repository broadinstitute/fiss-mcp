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

        # Verify all three Phase 1 tools are present
        assert "list_workspaces" in tool_names
        assert "get_workspace_data_tables" in tool_names
        assert "get_submission_status" in tool_names


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
            from terra_mcp.server import list_workspaces

            # Create mock context
            ctx = MagicMock()
            result = await list_workspaces(ctx)

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
            from terra_mcp.server import list_workspaces

            ctx = MagicMock()

            # Should raise ToolError with actionable message
            with pytest.raises(ToolError) as exc_info:
                await list_workspaces(ctx)

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
            from terra_mcp.server import get_workspace_data_tables

            ctx = MagicMock()
            result = await get_workspace_data_tables(
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
            from terra_mcp.server import get_workspace_data_tables

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_workspace_data_tables(
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
            from terra_mcp.server import get_workspace_data_tables

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_workspace_data_tables(
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
            from terra_mcp.server import get_submission_status

            ctx = MagicMock()
            result = await get_submission_status(
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
            from terra_mcp.server import get_submission_status

            ctx = MagicMock()
            result = await get_submission_status(
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
            from terra_mcp.server import get_submission_status

            ctx = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await get_submission_status(
                    workspace_namespace="test-ns",
                    workspace_name="test-ws",
                    submission_id="nonexistent",
                    ctx=ctx,
                )

            error_msg = str(exc_info.value)
            assert "not found" in error_msg
            assert "nonexistent" in error_msg
            assert "test-ns/test-ws" in error_msg
