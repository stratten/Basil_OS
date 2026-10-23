"""
Integration test for agent file operations with real LLM to verify standardized output formatting.

This test exercises the complete agent pipeline including:
1. Enhanced agent instructions with standardized file operation reporting
2. Real LLM model execution
3. File operation parsing and result formatting
4. End-to-end verification that the widget will display correct file information

This saves manual minion testing by programmatically testing the full flow.
"""

import pytest
import tempfile
from pathlib import Path

from api.services.agent_processing.lifecycle.execution_graph.agent_graph_runtime import execute_tool_enhanced_workflow


pytestmark = pytest.mark.manual


def _temporary_agent_file_workspace():
    """Create an isolated fixture inside the shell tool's allowed workspace root."""
    project_root = Path(__file__).resolve().parents[6]
    return tempfile.TemporaryDirectory(dir=project_root)


@pytest.mark.asyncio
async def test_agent_file_creation_with_standardized_output():
    """Test that the agent creates files and uses standardized STEP_COMPLETE format."""
    
    print("\n🤖 Testing Agent File Creation with Standardized Output...")
    
    # Create a temporary directory for the test
    with _temporary_agent_file_workspace() as temp_dir:
        temp_path = Path(temp_dir)
        test_file_path = temp_path / "agent-test-creation.txt"
        
        # Instruction that should trigger file creation
        instruction = f"Create a text file called 'agent-test-creation.txt' in the directory {temp_dir} with the content 'Hello from AI agent test!'"
        
        print(f"🎯 Testing instruction: {instruction}")
        print(f"📁 Target file: {test_file_path}")
        
        try:
            # Execute the agent workflow
            context = {"source": "integration_test", "session_id": "test_file_creation"}
            results = await execute_tool_enhanced_workflow(instruction, context)
            
            print(f"📊 Agent execution results:")
            print(f"   📦 Tools created: {results.get('tools_created', 0)}")
            print(f"   📋 Todos processed: {results.get('todos_processed', 0)}")
            print(f"   ⚡ Steps executed: {results.get('total_steps_executed', 0)}")
            print(f"   ✅ Steps completed: {results.get('steps_completed', 0)}")
            print(f"   ❌ Steps failed: {results.get('steps_failed', 0)}")
            
            # Check if we have workflow execution results
            workflow_result = results.get('workflow_result', '')
            # NEW: Validate finalizer envelope files payload
            envelope = results.get('final_envelope', {}) or {}
            payload = envelope.get('result_payload', {}) or {}
            files_payload = payload.get('files', []) or []
            print(f"📦 Finalizer payload files: {files_payload}")
            names = [f.get('name') for f in files_payload]
            paths = [f.get('full_path') for f in files_payload]
            assert 'agent-test-creation.txt' in names, "Finalizer should include created filename"
            assert any(str(test_file_path) in (p or '') for p in paths), "Finalizer should include full path to created file"
            assert workflow_result, "Agent should return non-empty workflow_result text"
            assert test_file_path.exists(), f"File should exist on disk: {test_file_path}"
            assert test_file_path.read_text(encoding="utf-8").strip() == "Hello from AI agent test!"

        except Exception as e:
            pytest.fail(f"Agent execution raised unexpectedly: {e}")


@pytest.mark.asyncio
async def test_agent_file_modification_with_standardized_output():
    """Test that the agent modifies files and uses standardized STEP_COMPLETE format."""
    
    print("\n📝 Testing Agent File Modification with Standardized Output...")
    
    # Create a temporary file to modify
    with _temporary_agent_file_workspace() as temp_dir:
        temp_path = Path(temp_dir)
        test_file_path = temp_path / "modify-test.txt"
        
        # Create the initial file
        test_file_path.write_text("Initial content for modification test.\n", encoding="utf-8")
        
        # Instruction that should trigger file modification
        instruction = f"Add the line 'This line was added by the AI agent!' to the existing file at {test_file_path}"
        
        print(f"🎯 Testing instruction: {instruction}")
        print(f"📁 Target file: {test_file_path}")
        
        try:
            # Execute the agent workflow
            context = {"source": "integration_test", "session_id": "test_file_modification"}
            results = await execute_tool_enhanced_workflow(instruction, context)
            
            print(f"📊 Agent execution results:")
            print(f"   📦 Tools created: {results.get('tools_created', 0)}")
            print(f"   📋 Todos processed: {results.get('todos_processed', 0)}")
            print(f"   ⚡ Steps executed: {results.get('total_steps_executed', 0)}")
            print(f"   ✅ Steps completed: {results.get('steps_completed', 0)}")
            
            # Check workflow results
            workflow_result = results.get('workflow_result', '')
            # NEW: Validate finalizer envelope files payload for modification
            envelope = results.get('final_envelope', {}) or {}
            payload = envelope.get('result_payload', {}) or {}
            files_payload = payload.get('files', []) or []
            print(f"📦 Finalizer payload files (modification): {files_payload}")
            names = [f.get('name') for f in files_payload]
            paths = [f.get('full_path') for f in files_payload]
            assert 'modify-test.txt' in names, "Finalizer should include modified filename"
            assert any(str(test_file_path) in (p or '') for p in paths), "Finalizer should include full path to modified file"
            assert workflow_result, "Agent should return non-empty workflow_result text"
            new_content = test_file_path.read_text(encoding="utf-8")
            assert "Initial content for modification test." in new_content, "Original content must be preserved"
            assert "This line was added by the AI agent!" in new_content, "Requested line must be appended"

        except Exception as e:
            pytest.fail(f"Agent execution raised unexpectedly: {e}")
