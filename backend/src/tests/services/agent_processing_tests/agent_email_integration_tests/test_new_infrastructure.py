"""
Test New Agent Processing Infrastructure

Tests the new ServiceCapabilityAnalyzer and ServiceExecutionEngine.
"""

import asyncio
import unittest
import sys
import os
import logging
import pytest

# Add project root to Python path
project_root = os.path.join(os.path.dirname(__file__), '../../..')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator

pytestmark = pytest.mark.manual

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)

# Test timeout - 5 minutes for comprehensive diagnostics
TEST_TIMEOUT_SECONDS = 300

class TestNewInfrastructure(unittest.TestCase):
    """Test cases for new agent processing infrastructure."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create the workflow coordinator - it handles its own dependencies
        self.workflow_coordinator = WorkflowCoordinator()
        
        self.test_context = {
            "active_app": "Mail",
            "screen_text": "Inbox view"
        }

    async def test_new_infrastructure_workflow(self):
        """Test new infrastructure through natural user instruction flow."""
        print("\n🧪 Testing new infrastructure workflow...")
        print("📝 User Instruction: Reply to my last 2 emails")
        print(f"🔍 Context: {self.test_context}")
        print("🚀 Starting workflow execution...")
        print("=" * 60)
        
        try:
            user_instruction = "Reply to my last 2 emails"
            
            # Phase 1: Execute the workflow planning through the coordinator with real LLM
            print("\n🎯 PHASE 1: WORKFLOW PLANNING")
            planning_result = await self.workflow_coordinator.coordinate_workflow_planning(
                user_instruction, self.test_context
            )
            
            print(f"✅ Workflow planned successfully")
            print(f"📝 Original Instruction: {planning_result.original_prompt}")
            print(f"🔧 Services Cached: {planning_result.capability_cache.total_services}")
            print(f"📊 Planning Duration: {planning_result.planning_duration:.3f}s")
            print(f"🏗️ Enhanced Todos Created: {len(planning_result.enhanced_todos)}")
            
            self.assertEqual(planning_result.original_prompt, user_instruction)
            self.assertIsNotNone(planning_result.capability_cache)
            self.assertGreater(planning_result.planning_duration, 0)
            self.assertGreater(len(planning_result.enhanced_todos), 0)
            
            # Phase 2: Execute the planned workflow
            print("\n🎯 PHASE 2: WORKFLOW EXECUTION")
            execution_result = await self.workflow_coordinator.execute_planned_workflow(planning_result)
            
            print(f"✅ Workflow executed successfully")
            print(f"📊 Todos Completed: {execution_result.todos_completed}")
            print(f"❌ Todos Failed: {execution_result.todos_failed}")
            print(f"⏱️ Execution Duration: {execution_result.total_execution_duration:.3f}s")
            print(f"🎯 Overall Success: {execution_result.overall_success}")
            
            # Show execution results summary
            print("\n📋 EXECUTION RESULTS SUMMARY:")
            for i, result in enumerate(execution_result.execution_results, 1):
                status = "✅" if result.success else "❌"
                print(f"   {status} Todo {i}: {result.todo_title}")
                print(f"      Steps: {result.steps_completed}/{result.total_steps}")
                if not result.success:
                    print(f"      Error: {result.error}")
                if result.step_results:
                    print(f"      Step Details:")
                    for step in result.step_results:
                        step_status = "✅" if step.get("success", False) else "❌"
                        print(f"        {step_status} {step.get('description', 'Unknown step')}")
                        if step.get("success") and step.get("result"):
                            result_data = step["result"]
                            if isinstance(result_data, dict):
                                print(f"          Result keys: {list(result_data.keys())}")
                            else:
                                print(f"          Result type: {type(result_data).__name__}")
            
            # Validate execution results
            self.assertIsNotNone(execution_result)
            self.assertEqual(len(execution_result.execution_results), len(planning_result.enhanced_todos))
            self.assertGreater(execution_result.total_execution_duration, 0)
            
            print("\n✅ New infrastructure end-to-end test passed!")
            
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            raise

async def run_tests():
    """Run all tests with timeout protection."""
    print("🚀 Running New Infrastructure Tests")
    print(f"⏰ Test timeout set to {TEST_TIMEOUT_SECONDS} seconds")
    print("=" * 50)
    
    # Create test instance
    test_instance = TestNewInfrastructure()
    test_instance.setUp()
    
    # Run the test with timeout
    print(f"\n📋 Running infrastructure test...")
    try:
        await asyncio.wait_for(
            test_instance.test_new_infrastructure_workflow(),
            timeout=TEST_TIMEOUT_SECONDS
        )
        print("✅ Infrastructure test passed")
        return True
    except asyncio.TimeoutError:
        print(f"⏰ Test timed out after {TEST_TIMEOUT_SECONDS} seconds")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(run_tests())
    if not success:
        exit(1) 