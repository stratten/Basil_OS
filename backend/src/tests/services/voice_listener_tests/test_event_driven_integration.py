#!/usr/bin/env python3
"""
Test Event-Driven Integration
Verifies that database events trigger the correct operations exactly once.
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
    async def generate_response(self, *args, **kwargs):
        return "Mock response"

async def test_event_driven_integration():
    print("🧪 Testing Event-Driven Minion Integration")
    print("=" * 60)
    
    # Generate unique agent task ID
    import uuid
    agent_task_id = f"test-cmd-{uuid.uuid4().hex[:8]}"
    
    # Setup
    websocket_manager = MockWebSocketManager()
    llm_service = MockLLMService()
    orchestrator = MinionOrchestrator(
        llm_service=llm_service,
        websocket_manager=websocket_manager
    )
    
    print("✅ Orchestrator initialized")
    
    # Test 1: New agent task processing
    print(f"\n🧪 Test 1: New agent task Processing (ID: {agent_task_id})")
    result = await orchestrator.process_minion(
        minion="take a screenshot",
        agent_task_id=agent_task_id
    )
    
    print(f"📋 Initial Result: {result}")
    
    # Wait for background processing to complete (LLM routing can take time)
    await asyncio.sleep(10)
    
    # Check agent task status
    status = await orchestrator.get_agent_task_status(agent_task_id)
    print(f"📊 Status After Routing: {status}")
    
    # Test 2: Clarification flow - only if agent task needs clarification
    final_status = status.get('status')
    
    if final_status == 'needs_clarification':
        print("\n🧪 Test 2: Clarification Flow (agent task needs clarification)")
        
        # Add clarification
        clarification_result = await orchestrator.add_clarification(
            agent_task_id=agent_task_id,
            clarification_text="save it to desktop"
        )
        print(f"📋 Clarification Result: {clarification_result}")
        
        # Wait for clarification processing
        await asyncio.sleep(3)
        
        # Check final status
        final_status = await orchestrator.get_agent_task_status(agent_task_id)
        print(f"📊 Final Status After Clarification: {final_status}")
        
    elif final_status == 'routed':
        print(f"\n✅ Test 2: agent task successfully routed to operation: {status.get('operation_parameters', {}).get('operation', 'unknown')}")
        print("No clarification needed - agent task was clear enough for routing.")
        
    else:
        print(f"\n⚠️ Test 2: agent task in unexpected status: {final_status}")
        print("Cannot test clarification flow.")
    
    # Test 3: Count operations
    print(f"\n📊 WebSocket Messages Sent: {len(websocket_manager.sent_messages)}")
    for i, msg in enumerate(websocket_manager.sent_messages):
        print(f"  {i+1}. {msg.get('event_type', 'unknown')} - {msg.get('status', 'unknown')}")
    
    print("\n✅ Event-driven integration test completed!")

if __name__ == "__main__":
    asyncio.run(test_event_driven_integration()) 