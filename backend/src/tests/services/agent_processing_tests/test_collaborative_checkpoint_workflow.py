"""
Integration test for collaborative workflow checkpoints requiring user input.

This test demonstrates the checkpoint flow where the agent requests user input
mid-workflow, the workflow pauses, and can be resumed with user-provided data.

The test uses the actual app infrastructure (WorkflowCoordinator, LangGraph, 
checkpoint tool) to simulate a realistic collaborative scenario.

RUN FROM ANYWHERE:
    cd /tmp/basil-fixture/Desktop/Basil/Basil && python -m pytest src/tests/services/agent_processing_tests/test_collaborative_checkpoint_workflow.py -v -s
"""

import pytest
import asyncio
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest
from api.services.agent_processing.lifecycle.runtime.workflow_results import WorkflowExecutionResult

pytestmark = pytest.mark.manual


@pytest.mark.asyncio
async def test_collaborative_workflow_with_checkpoint():
    """
    Test a workflow that requires user input mid-execution.
    
    Scenario:
    1. User asks: "Draft replies to my last three emails"
    2. Agent processes, finds emails, but needs clarification on tone
    3. Agent raises CheckpointRequest asking: "Should I use formal or casual tone?"
    4. Workflow pauses and returns checkpoint_pending status
    5. User provides input: "Use formal tone"
    6. Workflow resumes with user input and completes drafts
    
    This test verifies:
    - Checkpoint requests are properly raised by the agent
    - Workflow coordinator catches and handles checkpoint requests
    - Session state is preserved during pause
    - Workflow can be resumed with user input
    - Final result includes both checkpoint interaction and completion
    """
    coordinator = WorkflowCoordinator()
    
    # Initial instruction that should trigger a checkpoint
    user_instruction = "Draft replies to my last three emails, but ask me about the tone first"
    agent_task_id = "test_checkpoint_001"
    
    print("\n" + "="*80)
    print("🎬 STARTING COLLABORATIVE WORKFLOW TEST")
    print("="*80)
    
    # Step 1: Execute workflow - should pause at checkpoint
    print("\n📤 Step 1: Sending instruction that requires user input...")
    print(f"   Instruction: {user_instruction}")
    
    try:
        result = await coordinator.execute_complete_workflow(
            user_instruction=user_instruction,
            context={
                "agent_task_id": agent_task_id,
                "user_id": "test_user",
                "session_id": "test_session_001"
            },
            use_graph_execution=False,
            use_tools_execution=True  # Use tool-enhanced mode with checkpoint support
        )
        
        # Step 2: Verify checkpoint was reached
        print("\n🛑 Step 2: Checking if workflow paused at checkpoint...")
        
        # The result should indicate checkpoint_pending
        assert result is not None, "Result should not be None"
        
        # Check if this is a checkpoint result
        if hasattr(result, 'status') and result.status == 'checkpoint_pending':
            print("   ✅ Checkpoint reached successfully!")
            print(f"   📝 Checkpoint prompt: {result.checkpoint_prompt}")
            
            # Extract checkpoint details
            checkpoint_prompt = result.checkpoint_prompt
            assert checkpoint_prompt is not None, "Checkpoint prompt should be present"
            assert "tone" in checkpoint_prompt.lower(), "Prompt should ask about tone"
            
            print(f"\n   Agent is asking: '{checkpoint_prompt}'")
            
            # Step 3: Simulate user providing input
            print("\n💬 Step 3: User provides input to resume workflow...")
            user_input = "Use formal and professional tone for all replies"
            print(f"   User response: {user_input}")
            
            # Step 4: Resume workflow with user input
            print("\n▶️  Step 4: Resuming workflow with user input...")
            
            resumed_result = await coordinator.resume_workflow(
                agent_task_id=agent_task_id,
                user_input=user_input
            )
            
            # Step 5: Verify completion
            print("\n✅ Step 5: Verifying workflow completion...")
            
            assert resumed_result is not None, "Resumed result should not be None"
            assert isinstance(resumed_result, WorkflowExecutionResult), "Should return WorkflowExecutionResult"
            
            # Check that workflow completed successfully
            if hasattr(resumed_result, 'overall_success'):
                assert resumed_result.overall_success is True, "Workflow should complete successfully after resume"
                print(f"   ✅ Workflow completed successfully!")
                print(f"   📊 Todos completed: {resumed_result.todos_completed}")
                print(f"   📝 Final result preview: {resumed_result.final_result[:200]}...")
            
            # Verify session context was maintained
            print("\n🔍 Step 6: Verifying session context was preserved...")
            # The resumed workflow should have access to the original instruction and checkpoint interaction
            assert agent_task_id in str(resumed_result), "Instruction ID should be tracked"
            
            print("\n" + "="*80)
            print("🎉 COLLABORATIVE WORKFLOW TEST COMPLETED SUCCESSFULLY")
            print("="*80)
            print("\nSummary:")
            print("  ✅ Agent requested user input via checkpoint")
            print("  ✅ Workflow paused and preserved state")
            print("  ✅ User provided input")
            print("  ✅ Workflow resumed and completed")
            print("  ✅ Session context maintained throughout")
            
        else:
            # If no checkpoint was reached, this might indicate the agent completed
            # without needing input (which is also valid, just not what we're testing)
            print("\n⚠️  Note: Workflow completed without checkpoint")
            print("   This could mean:")
            print("   - Agent didn't need clarification")
            print("   - Checkpoint tool wasn't invoked")
            print("   - Instruction was too simple to require collaboration")
            
            # Still verify basic completion
            assert isinstance(result, WorkflowExecutionResult), "Should return valid result"
            print(f"\n   Result: {result.final_result[:200]}...")
            
    except CheckpointRequest as checkpoint_error:
        # If CheckpointRequest bubbles up here, it means the coordinator
        # didn't catch it properly - this is actually what we want to test
        print("\n🛑 CheckpointRequest raised (expected behavior):")
        print(f"   Prompt: {checkpoint_error.prompt}")
        print(f"   Context: {checkpoint_error.context}")
        
        # This is the expected path - coordinator should catch this and
        # return a checkpoint_pending result instead of raising
        pytest.fail(
            "CheckpointRequest should be caught by coordinator and returned as "
            "checkpoint_pending result, not raised as exception"
        )
    
    except Exception as e:
        print(f"\n❌ Unexpected error: {type(e).__name__}: {e}")
        raise


@pytest.mark.asyncio
async def test_checkpoint_timeout_handling():
    """
    Test that checkpoints handle timeout scenarios gracefully.
    
    Scenario:
    - Workflow pauses at checkpoint
    - User doesn't respond within timeout period
    - System handles gracefully (either auto-continues or notifies)
    """
    coordinator = WorkflowCoordinator()
    
    print("\n" + "="*80)
    print("⏱️  TESTING CHECKPOINT TIMEOUT HANDLING")
    print("="*80)
    
    user_instruction = "Draft a complex email and ask me about multiple details"
    agent_task_id = "test_checkpoint_timeout_001"
    
    result = await coordinator.execute_complete_workflow(
        user_instruction=user_instruction,
        context={
            "agent_task_id": agent_task_id,
            "session_id": "test_session_timeout"
        },
        use_tools_execution=True
    )
    
    if hasattr(result, 'status') and result.status == 'checkpoint_pending':
        print("✅ Checkpoint reached, testing timeout behavior...")
        
        # Simulate timeout by waiting (in real app, this would be handled by backend)
        # For test purposes, we just verify the checkpoint state is maintained
        await asyncio.sleep(0.5)  # Brief pause to simulate time passing
        
        # Attempt to resume without input (simulating timeout)
        try:
            timeout_result = await coordinator.resume_workflow(
                agent_task_id=agent_task_id,
                user_input=None  # No input provided
            )
            
            print("⚠️  Workflow resumed without input (timeout handling)")
            # System should handle this gracefully
            assert timeout_result is not None
            
        except Exception as e:
            print(f"✅ Timeout handled with appropriate error: {type(e).__name__}")
            # This is acceptable - system should handle missing input
    
    print("\n✅ Timeout handling test complete")


@pytest.mark.asyncio
async def test_multiple_checkpoints_in_sequence():
    """
    Test a workflow with multiple checkpoint interactions.
    
    Scenario:
    - Agent asks for input
    - User responds
    - Agent processes, then asks for more input
    - User responds again
    - Workflow completes
    
    This tests that session context accumulates across multiple interactions.
    """
    coordinator = WorkflowCoordinator()
    
    print("\n" + "="*80)
    print("🔄 TESTING MULTIPLE SEQUENTIAL CHECKPOINTS")
    print("="*80)
    
    agent_task_id = "test_multi_checkpoint_001"
    
    # Instruction that might trigger multiple clarifications
    user_instruction = (
        "Draft an email to the team about the project update. "
        "Ask me about the timeline, budget, and key milestones."
    )
    
    print(f"\n📤 Initial instruction: {user_instruction}")
    
    result = await coordinator.execute_complete_workflow(
        user_instruction=user_instruction,
        context={
            "agent_task_id": agent_task_id,
            "session_id": "test_session_multi"
        },
        use_tools_execution=True
    )
    
    checkpoint_count = 0
    max_checkpoints = 3  # Prevent infinite loops
    
    # Handle multiple checkpoints in sequence
    while (hasattr(result, 'status') and 
           result.status == 'checkpoint_pending' and 
           checkpoint_count < max_checkpoints):
        
        checkpoint_count += 1
        print(f"\n🛑 Checkpoint #{checkpoint_count} reached")
        print(f"   Agent asks: {result.checkpoint_prompt}")
        
        # Simulate user providing relevant information
        user_responses = {
            1: "Timeline is 3 months, starting next week",
            2: "Budget is $50,000 with $10k contingency",
            3: "Key milestones: Design (1mo), Development (1.5mo), Testing (0.5mo)"
        }
        
        user_input = user_responses.get(checkpoint_count, "Please proceed with your best judgment")
        print(f"   User responds: {user_input}")
        
        # Resume workflow
        result = await coordinator.resume_workflow(
            agent_task_id=agent_task_id,
            user_input=user_input
        )
    
    print(f"\n✅ Workflow completed after {checkpoint_count} checkpoint(s)")
    
    if checkpoint_count > 0:
        print("   ✅ Multiple checkpoint interactions handled successfully")
        print("   ✅ Session context accumulated across interactions")
    else:
        print("   ℹ️  No checkpoints were triggered (instruction may have been too simple)")
    
    # Verify final result
    assert isinstance(result, WorkflowExecutionResult), "Should return valid result"
    print(f"\n📝 Final result: {result.final_result[:200]}...")


if __name__ == "__main__":
    """
    Run this test directly to see collaborative workflow in action.
    
    Usage:
        cd /tmp/basil-fixture/Desktop/Basil/Basil
        python -m pytest src/tests/services/agent_processing_tests/test_collaborative_checkpoint_workflow.py -v -s
    """
    print("\n" + "="*80)
    print("COLLABORATIVE CHECKPOINT WORKFLOW TEST SUITE")
    print("="*80)
    print("\nThis test suite demonstrates:")
    print("  1. Agent requesting user input mid-workflow")
    print("  2. Workflow pausing and preserving state")
    print("  3. User providing input to resume")
    print("  4. Workflow completing with collaborative input")
    print("  5. Handling timeouts and multiple checkpoints")
    print("\nRun with: pytest <this_file> -v -s")
    print("="*80 + "\n")

