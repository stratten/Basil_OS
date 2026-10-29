import asyncio
import json
import websockets
import uuid
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_conversation_streaming():
    """Test the streaming functionality for regular conversations."""
    uri = "ws://localhost:8000/ws"
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("Connected to WebSocket server")
            
            # Create a conversation ID
            conversation_id = str(uuid.uuid4())
            logger.info(f"Using conversation ID: {conversation_id}")
            
            # Send a message with streaming enabled
            message = {
                "type": "conversation_message",  # Regular conversation, not history chat
                "message": "Tell me about quantum physics",
                "message_id": str(uuid.uuid4()),
                "conversation_id": conversation_id,
                "use_streaming": True  # Enable streaming
            }
            
            logger.info(f"Sending message: {message}")
            await websocket.send(json.dumps(message))
            
            # Wait for acknowledgment
            response = await websocket.recv()
            logger.info(f"Received acknowledgment: {response}")
            
            # Collect streaming tokens
            full_response = ""
            streaming_started = False
            
            # Listen for streaming tokens and other events
            while True:
                try:
                    # Set a timeout to avoid hanging indefinitely
                    response = await asyncio.wait_for(websocket.recv(), timeout=30)
                    event = json.loads(response)
                    
                    # Check event type
                    event_type = event.get("event_type")
                    
                    if event_type == "conversation_token":
                        # This is a streaming token
                        streaming_started = True
                        token = event.get("token", "")
                        full_response += token
                        
                        # Print token (or just a dot to avoid cluttering the console)
                        print(token, end="", flush=True)
                        
                        # Check if this is the final token
                        if event.get("is_final", False):
                            print("\n--- Streaming completed ---")
                            break
                    
                    elif event_type == "conversation_message":
                        # This is a complete message (non-streaming)
                        if not streaming_started:
                            logger.info(f"Received regular response instead of streaming: {event.get('message')[:50]}...")
                            full_response = event.get("message", "")
                            break
                    
                    elif event_type == "conversation_error":
                        # This is an error message
                        logger.error(f"Received error: {event.get('message')}")
                        break
                    
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for response")
                    break
                except Exception as e:
                    logger.error(f"Error receiving message: {e}")
                    break
            
            # Print the full response
            print(f"\n\nFull response:\n{full_response}")
            
    except Exception as e:
        logger.error(f"Error connecting to WebSocket server: {e}")

if __name__ == "__main__":
    asyncio.run(run_conversation_streaming())