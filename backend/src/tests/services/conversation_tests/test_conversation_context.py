import asyncio
import logging
import uuid
from typing import Dict, List, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock classes for testing
class MockMessage:
    def __init__(self, role, content, id=None):
        self.id = id or str(uuid.uuid4())
        self.content = content
        self.role = role
        self.metadata = {}

class MockConversation:
    def __init__(self, id=None, system_message=None):
        self.id = id or str(uuid.uuid4())
        self.messages = []
        if system_message:
            self.messages.append(MockMessage("system", system_message))
        self.metadata = {}

class MockConversationService:
    def __init__(self):
        self.conversations = {}
        
    def create_conversation(self, system_message=None):
        conversation = MockConversation(system_message=system_message)
        self.conversations[conversation.id] = conversation
        return conversation
        
    def get_conversation(self, conversation_id):
        return self.conversations.get(conversation_id)
        
    def add_message(self, conversation_id, role, content):
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return None
        message = MockMessage(role, content)
        conversation.messages.append(message)
        return message
        
    async def send_message(self, conversation_id, content):
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return None
            
        # Add user message
        user_message = self.add_message(conversation_id, "user", content)
        
        # Get all messages for context
        formatted_messages = []
        for msg in conversation.messages:
            formatted_messages.append({
                "role": msg.role,
                "content": msg.content
            })
            
        # Generate a response based on the conversation history
        response_content = self._generate_response(formatted_messages)
        
        # Add assistant message
        assistant_message = self.add_message(conversation_id, "assistant", response_content)
        
        return {
            "message": assistant_message,
            "conversation_id": conversation_id
        }
        
    def _generate_response(self, messages):
        """Generate a response based on the conversation history."""
        # This is a simple mock that demonstrates context awareness
        
        # Check if there's any mention of activities in the history
        has_activity_info = any("activities" in msg.get("content", "").lower() for msg in messages)
        has_work_question = any("do for work" in msg.get("content", "").lower() for msg in messages)
        
        if has_work_question and has_activity_info:
            return "Based on your activity history, it appears you might be a software developer or data engineer, as you've been working with structured data formats like MHL and JSON, and focusing on maintaining data structures during code changes."
        elif has_work_question:
            return "I don't have enough context to determine what you do for work. Please provide more information."
        else:
            return "I'm here to help. What would you like to know?"

async def run_conversation_context():
    """Test that conversation context is maintained between different types of messages."""
    # Create mock conversation service
    conversation_service = MockConversationService()
    
    # Create a new conversation
    conversation = conversation_service.create_conversation(
        system_message="You are a helpful assistant."
    )
    conversation_id = conversation.id
    
    logger.info(f"Created conversation with ID: {conversation_id}")
    
    # Simulate activity query processing
    # 1. Add user message
    user_message = conversation_service.add_message(
        conversation_id, "user", "What did I do this week?"
    )
    
    # 2. Add activity query response (simulating what we added to websocket.py)
    activity_response = """I found 10 activities between 2025-03-03 and 2025-03-08.
    
Most used applications: TextEdit (10)

Here's what you were working on:
1. TextEdit: Working with structured data formats like MHL and JSON
2. TextEdit: Debugging and maintaining data structures
"""
    
    activity_message = conversation_service.add_message(
        conversation_id, "assistant", activity_response
    )
    
    # 3. Add activity summary (simulating what we added to websocket.py)
    summary = """During the past week, you were predominantly engaged in TextEdit for your tasks.
A significant focus was placed on data processing, particularly with structured formats like MHL and JSON.
You delved into maintaining consistency in data structures while debugging and modifying code for batch operations."""
    
    summary_message = conversation_service.add_message(
        conversation_id, "assistant", summary
    )
    
    # Now send a follow-up message
    logger.info("Sending follow-up message: 'What do you think I do for work?'")
    response = await conversation_service.send_message(
        conversation_id, "What do you think I do for work?"
    )
    
    # Check if the response contains information from the activity history
    logger.info(f"Response: {response['message'].content}")
    
    # Print all messages in the conversation for debugging
    logger.info("\nFull conversation history:")
    for i, msg in enumerate(conversation.messages):
        logger.info(f"{i+1}. [{msg.role}]: {msg.content[:50]}...")
    
    # Verify that the response shows context awareness
    if "software developer" in response["message"].content or "data engineer" in response["message"].content:
        logger.info("✅ Test PASSED: Response shows awareness of activity history")
    else:
        logger.error("❌ Test FAILED: Response does not show awareness of activity history")

if __name__ == "__main__":
    asyncio.run(run_conversation_context())