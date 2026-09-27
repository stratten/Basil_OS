"""Activity summarization utilities for generating concise summaries of user activities."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set
import json
import logging
import time
import re

# Import required components
from ....core.models.model_invocation import call_model_with_prompt
from ....core.models.model_types import ModelCapability
from ....core.models.preferences import Preferences
from ....services.model_usage_service import ModelUsageService

logger = logging.getLogger(__name__)

async def generate_activity_summary(
    activities: List[Dict[str, Any]], 
    time_desc: str, 
    model_service = None,
    model_usage_service = None,
    model_id: Optional[str] = None
) -> Optional[str]:
    """Generate a concise summary of the activities using AI.
    
    Args:
        activities: List of activity dictionaries
        time_desc: Time description string (e.g., "between 2023-01-01 and 2023-01-02")
        model_service: Optional ModelService instance (deprecated, use model_usage_service instead)
        model_usage_service: Optional ModelUsageService for better model selection
        model_id: Optional specific model to use for processing
        
    Returns:
        A concise summary of the activities, or None if summarization failed
    """
    logger.info(f"=== ACTIVITY SUMMARIZATION STARTED ===")
    logger.info(f"Received {len(activities) if activities else 0} activities to summarize")
    logger.info(f"Time description: {time_desc}")
    logger.info(f"Model service available: {model_service is not None}")
    logger.info(f"Model usage service available: {model_usage_service is not None}")
    logger.info(f"Explicit model ID: {model_id}")
    
    if not activities or len(activities) == 0:
        logger.info("No activities to summarize, returning early")
        return "No activities found for this time period."
    
    # Check if we have any service available
    if not model_usage_service and not model_service:
        logger.warning("Neither model_usage_service nor model_service provided for activity summarization")
        return None
    
    try:
        # If we have the model_usage_service, use it
        if model_usage_service:
            logger.info("Using ModelUsageService for model selection")
            model = await model_usage_service.get_model_for_task(
                capabilities={ModelCapability.REASONING},
                explicit_model_id=model_id
            )
            
            if not model:
                logger.warning("No suitable model found via ModelUsageService")
                return None
                
            # Safely log model info - handle case where model might not have a name attribute
            try:
                model_identifier = getattr(model, 'model_name', getattr(model, 'model_id', str(model)))
                logger.info(f"ModelUsageService selected model: {model_identifier}")
            except Exception as e:
                logger.info(f"ModelUsageService selected model (identifier unavailable): {type(model).__name__}")
            
        # Fall back to direct ModelService usage for backward compatibility
        else:
            logger.info("Using direct ModelService for model selection (legacy approach)")
            # Get a reasoning model
            logger.info("Fetching available models from model service")
            # Call get_installed_models without await since it's not an async method
            available_models = model_service.get_installed_models()
            logger.info(f"Found {len(available_models)} installed model types")
            
            # Get user preference for reasoning model
            preferences = Preferences.load()
            preferred_model_name = preferences.models.reasoning_model
            logger.info(f"User's preferred reasoning model: {preferred_model_name}")
            
            # Try to find the model by name
            model_type = None
            model_variant = "base"
            
            # First, try to find by exact display name match
            for model_id, model_info in available_models.items():
                for variant, variant_info in model_info.get("variants", {}).items():
                    display_name = variant_info.get("name", "")
                    model_capabilities = variant_info.get("capabilities", [])
                    
                    # Check if model has reasoning capability
                    has_reasoning = "reasoning" in model_capabilities
                    
                    # Check if the display names match (case insensitive)
                    if display_name.lower() == preferred_model_name.lower() and has_reasoning:
                        logger.info(f"Found exact model match: {model_id}/{variant} (display name: {display_name})")
                        model_type = model_id
                        model_variant = variant
                        break
                if model_type:
                    break
            
            # If no exact match, try to find the model by simple substring match
            if not model_type:
                for model_id, model_info in available_models.items():
                    for variant, variant_info in model_info.get("variants", {}).items():
                        display_name = variant_info.get("name", "")
                        model_capabilities = variant_info.get("capabilities", [])
                        
                        # Check if model has reasoning capability
                        has_reasoning = "reasoning" in model_capabilities
                        
                        # Check if the preferred name is a substring of the display name (case insensitive)
                        if preferred_model_name.lower() in display_name.lower() and has_reasoning:
                            logger.info(f"Found substring model match: {model_id}/{variant} (display name: {display_name})")
                            model_type = model_id
                            model_variant = variant
                            break
                    if model_type:
                        break
            
            # If still no match, just use any reasoning model
            if not model_type:
                logger.info("No matching model found for user preference, using any available reasoning model")
                for model_id, model_info in available_models.items():
                    for variant, variant_info in model_info.get("variants", {}).items():
                        model_capabilities = variant_info.get("capabilities", [])
                        
                        # Check if model has reasoning capability
                        has_reasoning = "reasoning" in model_capabilities
                        
                        if has_reasoning:
                            logger.info(f"Using available reasoning model: {model_id}/{variant}")
                            model_type = model_id
                            model_variant = variant
                            break
                    if model_type:
                        break
            
            if not model_type:
                logger.warning("No reasoning models available for activity summary")
                return None
            
            logger.info(f"Selected model: {model_type}/{model_variant}")
            
            logger.info(f"Loading model {model_type}")
            model = await model_service.load_model(
                model_type,
                model_variant,
                {ModelCapability.REASONING}
            )
            
            if not model:
                logger.warning(f"Failed to load model {model_type} for activity summary")
                return None
                
        # At this point, we have a loaded model (from either path)
        logger.info("Model loaded successfully, preparing activity data for prompt")
        
        # Prepare activity data for the prompt
        activity_details = []
        for activity in activities[:20]:  # Limit to 20 activities to keep prompt size reasonable
            app = activity.get("app_name", "Unknown")
            title = activity.get("window_title", "")
            timestamp = activity.get("timestamp", "")
            
            # Format timestamp
            try:
                if isinstance(timestamp, str):
                    # Parse the ISO timestamp from database
                    dt = datetime.fromisoformat(timestamp)
                    
                    # If the datetime is naive (no timezone info), assume it's UTC
                    # since the database stores timestamps in UTC
                    if dt.tzinfo is None:
                        # Treat as UTC and convert to local time
                        dt = dt.replace(tzinfo=timezone.utc)
                        dt = dt.astimezone()
                    else:
                        # Already has timezone info, just convert to local
                        dt = dt.astimezone()
                    
                    # Format for display
                    timestamp = dt.strftime("%-I:%M %p")
                elif isinstance(timestamp, datetime):
                    # Handle datetime objects directly
                    if timestamp.tzinfo is None:
                        # Treat as UTC and convert to local time
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                        timestamp = timestamp.astimezone()
                    else:
                        timestamp = timestamp.astimezone()
                    
                    # Format for display
                    timestamp = timestamp.strftime("%-I:%M %p")
            except Exception as e:
                logger.warning(f"Error formatting timestamp {timestamp}: {e}")
                # Keep original timestamp if parsing fails
                pass
            
            # Get AI analysis if available
            ai_analysis = activity.get("ai_analysis", {})
            activity_type = ai_analysis.get("activity_type", "Unknown") if ai_analysis else "Unknown"
            context = ai_analysis.get("context", "") if ai_analysis else ""
            content_summary = ai_analysis.get("content_summary", "") if ai_analysis else ""
            
            activity_details.append({
                "app": app,
                "title": title,
                "timestamp": timestamp,
                "activity_type": activity_type,
                "context": context,
                "content_summary": content_summary
            })
        
        logger.info(f"Prepared {len(activity_details)} activities for summarization")
        
        # Create the prompt
        prompt = f"""You are an AI assistant that summarizes user activities in a personal, conversational way.
Create a concise, informative summary of the following activities{time_desc}, addressing the user directly as "you".

Activities:
"""
        
        for i, activity in enumerate(activity_details):
            prompt += f"\n{i+1}. {activity['app']} at {activity['timestamp']}:\n"
            prompt += f"   Title: {activity['title']}\n"
            if activity['activity_type'] != "Unknown":
                prompt += f"   Activity Type: {activity['activity_type']}\n"
            if activity['context']:
                prompt += f"   Context: {activity['context']}\n"
            if activity['content_summary']:
                prompt += f"   Content Summary: {activity['content_summary']}\n"
        
        prompt += """
Based on the above activities, provide a concise, human-readable summary that:
1. Identifies the time period and duration of activity
2. Summarizes the main applications used
3. Describes the primary tasks or topics the user was working on
4. Highlights any patterns or themes in the activities
5. Uses natural, conversational language

IMPORTANT: Use personal language addressing the user directly as "you" instead of "the user" or "the individual". For example, say "You spent time working on..." instead of "The user spent time working on...".

Your summary should be 2-3 paragraphs at most and focus on giving the user a clear understanding of how they spent their time.
"""
        
        logger.info(f"Prompt created with {len(prompt)} characters")
        logger.info(f"Generating summary using model: {getattr(model, 'name', 'unknown')}")
        
        # Generate the summary. Routed through call_model_with_prompt because
        # local models (LlamaCppModel) do not accept enable_web_search and
        # passing it unconditionally raises TypeError.
        summary = await call_model_with_prompt(
            model, prompt=prompt, max_tokens=500, enable_web_search=False
        )
        
        logger.info(f"Summary generated successfully with {len(summary)} characters")
        logger.info("=== ACTIVITY SUMMARIZATION COMPLETED ===")
        
        return summary
    
    except Exception as e:
        logger.error(f"Error generating activity summary: {e}", exc_info=True)
        logger.info("=== ACTIVITY SUMMARIZATION FAILED ===")
        return None 