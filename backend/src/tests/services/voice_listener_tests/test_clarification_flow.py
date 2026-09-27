#!/usr/bin/env python3
"""
Test Event-Driven Minion Clarification Flow
Tests that vague instructions trigger the clarification flow properly.
"""

import asyncio
import sys
import os
import pytest
sys.path.append('src')

from api.services.agent_processing.lifecycle.submission.agent_task_processing import AgentTaskOrchestrator as MinionOrchestrator
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

pytestmark = pytest.mark.manual

class MockWebSocketManager:
    def __init__(self):
        self.sent_messages = []
    
    async def broadcast(self, message_data):
        self.sent_messages.append(message_data)
        print(f"📡 WebSocket: {message_data}")
    
    async def send_to_all(self, message_data):
        """Alias for broadcast to match the interface expected by orchestrator."""
        await self.broadcast(message_data)

class MockLLMService:
    async def chat_completion_streaming(self, messages, **kwargs):
        # For "do something" - return a clarification request
        user_message = next((msg['content'] for msg in messages if msg['role'] == 'user'), '')
        
        if 'do something' in user_message.lower():
            # This should trigger clarification
            mock_response = {
                "operation": "unknown",
                "confidence": 0.2,
                "requires_clarification": True,
                "clarification_question": "What specific action would you like me to perform? For example: take a screenshot, generate text, or open an application.",
                "reasoning": "The instruction 'do something' is too vague to determine a specific operation.",
                "parameters": {}
            }
        else:
            # For clarified instructions, return an operation
            mock_response = {
                "operation": "capture_screen",
                "confidence": 0.9,
                "requires_clarification": False,
                "clarification_question": None,
                "reasoning": "User wants to capture the screen.",
                "parameters": {"format": "png"}
            }
        
        import json
        yield json.dumps(mock_response)

async def test_clarification_flow():
    print("🧪 Testing Event-Driven Minion Clarification Flow")
    print("=" * 60)
    
    # Generate unique instruction ID
    import uuid
    agent_task_id = f"test-clarify-{uuid.uuid4().hex[:8]}"
    
    # Setup
    websocket_manager = MockWebSocketManager()
    llm_service = MockLLMService()
    orchestrator = MinionOrchestrator(
        llm_service=llm_service,
        websocket_manager=websocket_manager
    )
    
    print("✅ Orchestrator initialized")
    
    # Test 1: Vague instruction that should trigger clarification
    print(f"\n🧪 Test 1: Vague Instruction (ID: {agent_task_id})")
    result = await orchestrator.process_minion(
        minion="do something",
        agent_task_id=agent_task_id
    )
    print(f"📋 Process Result: {result}")
    
    # Wait for routing to complete (LLM takes time)
    await asyncio.sleep(10)
    
    # Check instruction status
    status = await orchestrator.get_agent_task_status(agent_task_id)
    print(f"📊 Status After Routing: {status}")
    
    final_status = status.get('status')
    
    if final_status == 'needs_clarification':
        print("\n✅ SUCCESS: Instruction correctly identified as needing clarification")
        
        # Test 2: Add clarification and verify it processes
        print("\n🧪 Test 2: Adding Clarification")
        clarification_result = await orchestrator.add_clarification(
            agent_task_id=agent_task_id,
            clarification_text="take a screenshot"
        )
        print(f"📋 Clarification Result: {clarification_result}")
        
        # Wait for clarified processing
        await asyncio.sleep(10)
        
        # Check final status
        final_status_after_clarification = await orchestrator.get_agent_task_status(agent_task_id)
        print(f"📊 Final Status After Clarification: {final_status_after_clarification}")
        
        if final_status_after_clarification.get('status') == 'completed':
            print("\n✅ SUCCESS: Clarification flow completed successfully")
        else:
            print(f"\n❌ FAILED: Expected 'completed' status, got {final_status_after_clarification.get('status')}")
            
    elif final_status == 'completed':
        print("\n⚠️ UNEXPECTED: Instruction completed without clarification")
        print("This suggests the LLM didn't recognize 'do something' as vague")
        
    else:
        print(f"\n❌ FAILED: Unexpected status: {final_status}")
    
    # Summary
    print(f"\n📊 WebSocket Messages Sent: {len(websocket_manager.sent_messages)}")
    print("\n🏁 Clarification Flow Test Complete")

if __name__ == "__main__":
    asyncio.run(test_clarification_flow()) 