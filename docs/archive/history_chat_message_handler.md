# Archived: `history_chat_message` WebSocket handler

Removed from `backend/src/api/routes/websocket_routes/conversation.py` on 2026-09-29. No client sends a `/ws` frame with `type: "history_chat_message"`: BasilClient and every web component route conversation turns through `conversation_message`, and activity-history questions are answered by the agent's recall and history tools. The outgoing `history_chat_event` stream it produced is still emitted by other paths (for example the hotkey router) and was not changed.

The handler is kept here because it contains non-trivial behavior that may be worth reusing: a two-mode flow (plain Conversation Service turn versus activity-database query), user-facing timeframe formatting for ISO timestamps with and without zones, a per-application activity digest capped at ten entries, and a follow-up LLM summary through `generate_activity_summary`. It also has known defects that would need fixing before any revival: `conversation_service.add_message` is called without `await` on three paths, and its `{status, message}` acknowledgments lack the `event_type` every other `/ws` reply carries.

Dependencies it took from the `/ws` endpoint (`QueryIntentHandler`, `ModelService`, `ModelUsageService`) were removed from `websocket_endpoint` along with it.

## Dispatch branch (formerly in `backend/src/api/routes/websocket.py`)

```python
                            # Handle history chat messages
                            elif msg_data.get("type") == "history_chat_message":
                                await handle_history_chat_message(
                                    websocket,
                                    msg_data,
                                    get_conversation_service,
                                    get_query_intent_handler,
                                    model_service,
                                    model_usage_service,
                                    send_history_chat_event
                                    )
```

## Handler (formerly in `backend/src/api/routes/websocket_routes/conversation.py`)

```python
async def handle_history_chat_message(
    websocket,
    msg_data,
    get_conversation_service,
    get_query_intent_handler,
    model_service,
    model_usage_service,
    send_history_chat_event
):
    logger = logging.getLogger(__name__)
    logger.info("Received history chat message")

    message = msg_data.get("message", "")
    context = msg_data.get("context")
    query_activity_database = msg_data.get("query_activity_database", True)
    conversation_id = msg_data.get("conversation_id")
    message_id = msg_data.get("message_id", str(uuid.uuid4()))
    model_id = msg_data.get("model_id")

    if not message:
        logger.warning("Received empty message")
        await websocket.send_json({
            "status": "error",
            "message": "Empty message received"
        })
        return

    if model_id:
        logger.info(f"Using explicitly selected model for history chat: {model_id}")

    await websocket.send_json({
        "status": "success",
        "message": "Message received"
    })

    if not query_activity_database:
        logger.info("Not querying activity database, routing to Conversation Service")
        try:
            conversation_service = get_conversation_service()
            if not conversation_id:
                logger.info("No conversation ID provided, creating new conversation")
                conversation = await conversation_service.create_conversation(
                    system_message="You are Basil, an intelligent assistant designed to be genuinely helpful, conversational, and insightful. You can engage in natural conversation while also providing practical assistance. When users ask casual questions like 'How are you?', respond naturally. When they need help with tasks, provide clear, actionable guidance. Adapt your communication style to match the context - be concise when brevity is needed, detailed when complexity requires it, and always aim to be more helpful than a standard LLM interaction."
                )
                conversation_id = conversation.id
                logger.info(f"Created new conversation with ID: {conversation_id}")
            await send_history_chat_event(
                active=True,
                message=message,
                message_type="user",
                context=context,
                is_loading=False,
                message_id=message_id,
                conversation_id=conversation_id
            )
            await send_history_chat_event(
                active=True,
                message="",
                message_type="assistant",
                context=context,
                is_loading=True,
                message_id=None,
                conversation_id=conversation_id
            )
            response = await conversation_service.send_message(
                conversation_id=conversation_id,
                content=message,
                model_id=model_id
            )
            await send_history_chat_event(
                active=True,
                message=response.message.content,
                message_type="assistant",
                context=context,
                is_loading=False,
                message_id=response.message.id,
                conversation_id=conversation_id
            )
            logger.info(f"Sent response from Conversation Service: {response.message.content[:50]}...")
        except Exception as e:
            logger.error(f"Error routing to Conversation Service: {e}")
            await send_history_chat_event(
                active=True,
                message=f"Error: {str(e)}",
                message_type="error",
                context=context,
                is_loading=False,
                message_id=None,
                conversation_id=conversation_id
            )
        return
    await send_history_chat_event(
        active=True,
        message=message,
        message_type="user",
        context=context,
        is_loading=False,
        message_id=message_id,
        conversation_id=conversation_id
    )
    conversation_service = get_conversation_service()
    is_new_conversation = not conversation_id
    if is_new_conversation:
        logger.info("No conversation ID provided, creating new conversation")
        conversation = await conversation_service.create_conversation(
            system_message="You are Basil, an intelligent assistant designed to be genuinely helpful, conversational, and insightful. You can engage in natural conversation while also providing practical assistance. When users ask casual questions like 'How are you?', respond naturally. When they need help with tasks, provide clear, actionable guidance. Adapt your communication style to match the context - be concise when brevity is needed, detailed when complexity requires it, and always aim to be more helpful than a standard LLM interaction."
        )
        conversation_id = conversation.id
        logger.info(f"Created new conversation with ID: {conversation_id}")
    await conversation_service.add_message(conversation_id, "user", message)
    if is_new_conversation:
        asyncio.ensure_future(conversation_service._auto_title_conversation(conversation_id, message))
    await send_history_chat_event(
        active=True,
        message="",
        message_type="assistant",
        context=context,
        is_loading=True,
        message_id=None,
        conversation_id=conversation_id
    )
    try:
        logger.info(f"Processing history query: '{message}'")
        logger.info(f"Options: query_activity_database={query_activity_database}")
        query_intent_handler = get_query_intent_handler()
        response = await query_intent_handler.process_query(
            query_text=message,
            model_id=model_id
        )

        # Check if the response contains an error
        if "error" in response:
            error_message = response.get("error", "Unknown error occurred during query processing")
            logger.error(f"Query processing failed: {error_message}")
            await send_history_chat_event(
                active=True,
                message=f"I encountered an error while processing your query: {error_message}\n\nPlease try rephrasing your request or check that the necessary AI models are available.",
                message_type="assistant",
                context=context,
                is_loading=False,
                message_id=None,
                conversation_id=conversation_id
            )
            conversation_service.add_message(conversation_id, "assistant", f"Error: {error_message}")
            return

        activities = response.get("activities", [])
        timeframe = response.get("timeframe", {})
        model_used = response.get("model_id")
        if model_used:
            logger.info(f"Query processed using model: {model_used}")
        if activities:
            activity_count = len(activities)
            time_desc = ""
            if timeframe:
                start_time = timeframe.get("start")
                end_time = timeframe.get("end")
                # Debug: Log the actual timestamp values we received
                logger.debug(f"Received timeframe timestamps: start={start_time!r}, end={end_time!r}")
                if start_time and end_time:
                    # Convert backend timestamps to user-friendly format
                    try:
                        # Parse and format start time - handle multiple ISO formats
                        if isinstance(start_time, str):
                            # Try different parsing approaches for ISO format variations
                            start_time_clean = start_time.replace('Z', '+00:00') if 'Z' in start_time else start_time
                            # Handle timestamps without timezone info by treating as local
                            if '+' not in start_time_clean and 'Z' not in start_time:
                                start_dt = datetime.fromisoformat(start_time_clean)
                            else:
                                start_dt = datetime.fromisoformat(start_time_clean)
                            start_formatted = start_dt.astimezone().strftime("%-m/%-d/%Y %-I:%M %p")
                        else:
                            start_formatted = start_time.strftime("%-m/%-d/%Y %-I:%M %p")

                        # Parse and format end time - handle multiple ISO formats
                        if isinstance(end_time, str):
                            # Try different parsing approaches for ISO format variations
                            end_time_clean = end_time.replace('Z', '+00:00') if 'Z' in end_time else end_time
                            # Handle timestamps without timezone info by treating as local
                            if '+' not in end_time_clean and 'Z' not in end_time:
                                end_dt = datetime.fromisoformat(end_time_clean)
                            else:
                                end_dt = datetime.fromisoformat(end_time_clean)
                            end_formatted = end_dt.astimezone().strftime("%-m/%-d/%Y %-I:%M %p")
                        else:
                            end_formatted = end_time.strftime("%-m/%-d/%Y %-I:%M %p")

                        time_desc = f" between {start_formatted} and {end_formatted}"
                    except Exception as e:
                        # Enhanced error logging with more details about the timestamp format
                        logger.warning(f"Failed to parse timeframe timestamps for display: start={start_time!r} (type: {type(start_time)}), end={end_time!r} (type: {type(end_time)}), error={e}")
                        # Fallback to original format if parsing fails
                        time_desc = f" between {start_time} and {end_time}"
                elif start_time:
                    try:
                        # Parse and format start time - handle multiple ISO formats
                        if isinstance(start_time, str):
                            # Try different parsing approaches for ISO format variations
                            start_time_clean = start_time.replace('Z', '+00:00') if 'Z' in start_time else start_time
                            # Handle timestamps without timezone info by treating as local
                            if '+' not in start_time_clean and 'Z' not in start_time:
                                start_dt = datetime.fromisoformat(start_time_clean)
                            else:
                                start_dt = datetime.fromisoformat(start_time_clean)
                            start_formatted = start_dt.astimezone().strftime("%-m/%-d/%Y %-I:%M %p")
                        else:
                            start_formatted = start_time.strftime("%-m/%-d/%Y %-I:%M %p")
                        time_desc = f" after {start_formatted}"
                    except Exception as e:
                        logger.warning(f"Failed to parse start timestamp for display: {start_time!r} (type: {type(start_time)}), error={e}")
                        time_desc = f" after {start_time}"
                elif end_time:
                    try:
                        # Parse and format end time - handle multiple ISO formats
                        if isinstance(end_time, str):
                            # Try different parsing approaches for ISO format variations
                            end_time_clean = end_time.replace('Z', '+00:00') if 'Z' in end_time else end_time
                            # Handle timestamps without timezone info by treating as local
                            if '+' not in end_time_clean and 'Z' not in end_time:
                                end_dt = datetime.fromisoformat(end_time_clean)
                            else:
                                end_dt = datetime.fromisoformat(end_time_clean)
                            end_formatted = end_dt.astimezone().strftime("%-m/%-d/%Y %-I:%M %p")
                        else:
                            end_formatted = end_time.strftime("%-m/%-d/%Y %-I:%M %p")
                        time_desc = f" before {end_formatted}"
                    except Exception as e:
                        logger.warning(f"Failed to parse end timestamp for display: {end_time!r} (type: {type(end_time)}), error={e}")
                        time_desc = f" before {end_time}"
            app_counts = {}
            for activity in activities:
                app_name = activity.get("app_name", "Unknown")
                app_counts[app_name] = app_counts.get(app_name, 0) + 1
            app_summary = ", ".join([f"{app} ({count})" for app, count in sorted(
                app_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]])
            response_message = f"I found {activity_count} activities{time_desc}.\n\n"
            response_message += f"Most used applications: {app_summary}"
            if activity_count > 0:
                response_message += "\n\n**Here's what you were working on:**\n"
                for i, activity in enumerate(activities[:10]):
                    app = activity.get("app_name", "Unknown")
                    title = activity.get("window_title", "")
                    timestamp = activity.get("timestamp", "")
                    try:
                        if isinstance(timestamp, str):
                            # Parse and format timestamp - handle multiple ISO format variations
                            # Try different parsing approaches for ISO format variations
                            timestamp_clean = timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp
                            # Handle timestamps without timezone info by treating as UTC (since DB stores in UTC)
                            if '+' not in timestamp_clean and 'Z' not in timestamp:
                                # Assume UTC if no timezone info
                                dt = datetime.fromisoformat(timestamp_clean)
                                # Treat as UTC and convert to local timezone
                                dt = dt.replace(tzinfo=timezone.utc)
                                local_dt = dt.astimezone()
                            else:
                                # Has timezone info, parse normally
                                dt = datetime.fromisoformat(timestamp_clean)
                                local_dt = dt.astimezone()
                            timestamp = local_dt.strftime("%I:%M %p")
                        else:
                            # Direct datetime object
                            if timestamp.tzinfo is None:
                                # Assume UTC if no timezone info
                                timestamp = timestamp.replace(tzinfo=timezone.utc).astimezone()
                            else:
                                timestamp = timestamp.astimezone()
                            timestamp = timestamp.strftime("%I:%M %p")
                    except Exception as e:
                        logger.warning(f"Failed to parse activity timestamp for display: {timestamp!r} (type: {type(timestamp)}), error={e}")
                        # Keep original format if parsing fails
                        pass
                    response_message += f"\n**{i+1}. {app} at {timestamp}:**\n"

                    # Helper function to format multi-line content with proper indentation
                    def format_field(label, content):
                        if not content:
                            return ""
                        # Split content into lines and handle indentation
                        lines = str(content).strip().split('\n')
                        if len(lines) == 1:
                            return f"   **{label}:** {lines[0]}\n"
                        else:
                            # First line with label, subsequent lines indented with more spaces for better alignment
                            result = f"   **{label}:** {lines[0]}\n"
                            indent = "        "  # Use 8 spaces for better visual indentation
                            for line in lines[1:]:
                                result += f"{indent}{line.strip()}\n"
                            return result

                    response_message += format_field("Title", title)

                    # Remove extracted text and skills to make output cleaner and less technical
                    # extracted_text = activity.get("extracted_text", "")
                    # if extracted_text and len(extracted_text) > 0:
                    #     max_length = 200
                    #     if len(extracted_text) > max_length:
                    #         extracted_text = extracted_text[:max_length] + "..."
                    #     extracted_text = " ".join(extracted_text.split())
                    #     response_message += format_field("Content", extracted_text)

                    ai_analysis = activity.get("ai_analysis", {})
                    if ai_analysis and isinstance(ai_analysis, dict):
                        summary = ai_analysis.get("summary", "")
                        if summary and len(summary) > 0:
                            response_message += format_field("Summary", summary)

                        activity_type = ai_analysis.get("activity_type")
                        context = ai_analysis.get("context")
                        content_summary = ai_analysis.get("content_summary")
                        # skills = ai_analysis.get("skills", [])

                        if activity_type:
                            response_message += format_field("Activity Type", activity_type)
                        if context:
                            response_message += format_field("Context", context)
                        if content_summary:
                            response_message += format_field("Content Summary", content_summary)
                        # Remove skills field for cleaner output
                        # if skills and len(skills) > 0:
                        #     skills_str = ", ".join(skills[:5])
                        #     response_message += format_field("Skills", skills_str)
                if activity_count > 10:
                    response_message += f"\n...and {activity_count - 10} more activities."
        else:
            response_message = "I couldn't find any activities matching your query."
            logger.info("No activities found, sending 'no results found' message")
        logger.info(f"Sending response message: '{response_message[:50]}...' with message_type='assistant', is_loading=False")
        await send_history_chat_event(
            active=True,
            message=response_message,
            message_type="assistant",
            context=context,
            is_loading=False,
            message_id=None,
            conversation_id=conversation_id
        )
        conversation_service.add_message(conversation_id, "assistant", response_message)
        if activities and len(activities) > 0:
            logger.info(f"Starting activity summarization process for {len(activities)} activities")
            await send_history_chat_event(
                active=True,
                message="",
                message_type="assistant",
                context=context,
                is_loading=True,
                message_id=None,
                conversation_id=conversation_id
            )
            logger.info("Sent loading event for summary")
            logger.info(f"Calling generate_activity_summary with {len(activities)} activities")
            summary = await generate_activity_summary(
                activities=activities,
                time_desc=time_desc,
                model_service=model_service,
                model_usage_service=model_usage_service,
                model_id=model_id
            )
            logger.info(f"Summary generation completed: {summary is not None}")
            if summary:
                logger.info(f"Sending summary as follow-up message ({len(summary)} characters)")
                # Clean up markdown heading syntax that displays as literal hashtags
                cleaned_summary = summary.replace('## ', '').replace('#', '')  # Remove markdown headers
                await send_history_chat_event(
                    active=True,
                    message=cleaned_summary,
                    message_type="assistant",
                    context=context,
                    is_loading=False,
                    message_id=None,
                    conversation_id=conversation_id
                )
                conversation_service.add_message(conversation_id, "assistant", cleaned_summary)
                logger.info("Summary sent successfully")
            else:
                logger.warning("No summary was generated, skipping follow-up message")
    except Exception as e:
        logger.error(f"Error processing history query: {e}")
        await send_history_chat_event(
            active=True,
            message=f"Error: {str(e)}",
            message_type="error",
            context=context,
            is_loading=False,
            message_id=message_id,
            conversation_id=conversation_id
        )
```
