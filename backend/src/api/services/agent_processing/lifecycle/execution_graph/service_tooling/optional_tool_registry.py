"""Optional/internal tool registration for service tool creation."""

from typing import Dict, List

from .models import BaseTool
from .memory_tools import create_memory_tools
from .skill_tools import create_skill_tools


def should_register_provider_catalog(factory: object) -> bool:
    """Return whether this workflow pass may expose provider catalog actions."""
    return bool(getattr(factory, "allow_provider_catalog", True))


def should_register_delegated_agent(factory: object) -> bool:
    """Return whether this AgentTask is permitted to create child AgentTasks."""
    return bool(getattr(factory, "allow_delegated_agent", True))


def should_register_child_interaction_tools(factory: object) -> bool:
    """Return whether this AgentTask may request user input or parent context."""
    return bool(getattr(factory, "allow_child_interaction_tools", True))


def register_optional_tools(
    factory,
    tools: List[BaseTool],
    tool_map: Dict[str, BaseTool],
    optional_warnings: List[str],
) -> None:
    """Register optional tools without failing overall service tool creation."""
    profile = getattr(factory, "profile", None)

    # Add checkpoint tool for collaborative workflows - allows agent to request user input
    if should_register_child_interaction_tools(factory):
        try:
            from ....tools.internal_basil_tools.checkpoint_tool import create_checkpoint_tool
            checkpoint_tool = create_checkpoint_tool(profile=profile)
            tools.append(checkpoint_tool)
            tool_map["checkpoint.request_user_input"] = checkpoint_tool
            factory.logger.info("   ✅ Added request_user_input checkpoint tool")
        except Exception as e:
            err = f"Failed to add checkpoint tool: {e}"
            optional_warnings.append(err)
            factory.logger.warning(f"   ⚠️ {err}")
    else:
        factory.logger.info("   ⏭️ Skipped request_user_input for constrained child AgentTask")

    # Add the complementary local-history retrieval surfaces: chronological
    # event enumeration and scoped search/detail hydration.
    try:
        from ....tools.internal_basil_tools.retrieval_tool import create_retrieval_tool
        retrieval_tool = create_retrieval_tool(profile=profile)
        tools.append(retrieval_tool)
        tool_map["retrieval.basil_history"] = retrieval_tool
        factory.logger.info("   ✅ Added retrieve_basil_history tool")
    except Exception as e:
        err = f"Failed to add retrieval tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    try:
        from ....tools.internal_basil_tools.unified_history_tool import create_unified_history_tool
        unified_history_tool = create_unified_history_tool(profile=profile)
        tools.append(unified_history_tool)
        tool_map["retrieval.unified_history"] = unified_history_tool
        factory.logger.info("   ✅ Added query_unified_history tool")
    except Exception as e:
        err = f"Failed to add query_unified_history tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add activity query tool for querying user activity history
    try:
        from ....tools.internal_basil_tools.activity_query_tool import create_activity_query_tool
        activity_tool = create_activity_query_tool(profile=profile)
        tools.append(activity_tool)
        tool_map["activity.query"] = activity_tool
        factory.logger.info("   ✅ Added query_activities tool")
    except Exception as e:
        err = f"Failed to add activity query tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add task-chain and Conversation recall as ordinary, first-pass tools.
    # Conversation recall receives a per-turn captured id when this task was
    # delegated from Conversation; history/detail remain usable otherwise.
    if should_register_child_interaction_tools(factory):
        try:
            from ....tools.internal_basil_tools.recall import (
                create_recall_conversations_tools,
                create_recall_tools,
            )

            recall_root = getattr(factory, "current_root_task_id", None)
            recall_current = getattr(factory, "current_agent_task_id", None)
            recall_conversation_id = getattr(factory, "current_conversation_id", None)
            recall_tools = [
                *create_recall_tools(
                    profile=profile,
                    root_task_id=recall_root,
                    current_agent_task_id=recall_current,
                ),
                *create_recall_conversations_tools(
                    profile=profile,
                    current_conversation_id=recall_conversation_id,
                ),
            ]
            for recall_tool in recall_tools:
                tools.append(recall_tool)
                tool_map[f"recall.{recall_tool.name}"] = recall_tool
            factory.logger.info(
                "   ✅ Added recall tools (root=%s conversation=%s)",
                recall_root,
                recall_conversation_id,
            )
        except Exception as e:
            err = f"Failed to add recall tools: {e}"
            optional_warnings.append(err)
            factory.logger.warning(f"   ⚠️ {err}")
    else:
        factory.logger.info("   ⏭️ Skipped recall tools for constrained child AgentTask")

    # Add generic iterative work ledger for large or unknown-cardinality tasks
    try:
        from ....tools.internal_basil_tools.iterative_work_tool import create_iterative_work_tool
        iterative_work_tool = create_iterative_work_tool(profile=profile)
        tools.append(iterative_work_tool)
        tool_map["iterative_work.manage"] = iterative_work_tool
        factory.logger.info("   ✅ Added iterative_work ledger tool")
    except Exception as e:
        err = f"Failed to add iterative work tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add working memory tools. These use Basil's bounded markdown memory
    # store, not the activity/knowledge retrieval subsystem.
    try:
        memory_tools = create_memory_tools(profile=profile)
        tools.extend(memory_tools)
        for memory_tool in memory_tools:
            tool_map[f"memory.{memory_tool.name.split('_', 1)[1]}"] = memory_tool
        factory.logger.info("   ✅ Added working memory tools")
    except Exception as e:
        err = f"Failed to add working memory tools: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add skill catalog tools. Skill bodies load only on demand so the
    # catalog can scale without pre-injecting every SKILL.md into context.
    try:
        skill_tools = create_skill_tools(profile=profile)
        tools.extend(skill_tools)
        for skill_tool in skill_tools:
            tool_map[f"skill.{skill_tool.name.split('_', 1)[1]}"] = skill_tool
        factory.logger.info("   ✅ Added skill catalog tools")
    except Exception as e:
        err = f"Failed to add skill catalog tools: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add To-Do tools: available to every task for creation, and additionally
    # scoped to note-append/delegate only for a To-Do workspace manager task.
    try:
        from api.services.todos.tools import create_todo_tools

        todo_service = getattr(factory, "todo_service", None)
        if todo_service is None:
            raise RuntimeError("factory.todo_service is not configured")
        from api.services.todos.agent_task_bridge import get_todo_agent_task_bridge

        bridge = get_todo_agent_task_bridge()
        launcher = bridge.launch_todo_item_agent_task if bridge is not None else None
        todo_tools = create_todo_tools(
            todo_service=todo_service,
            agent_task_id=getattr(factory, "current_agent_task_id", None),
            agent_task_provider=getattr(todo_service, "agent_task_service", None),
            launcher=launcher,
        )
        for todo_tool in todo_tools:
            tools.append(todo_tool)
            tool_map[f"todos.{todo_tool.name}"] = todo_tool
        factory.logger.info("   ✅ Added To-Do tools (create/list/inspect/note/delegate)")
    except Exception as e:
        err = f"Failed to add To-Do tools: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add scheduled agent task creation tool for voice-driven scheduling flows
    try:
        from ....tools.internal_basil_tools.scheduled_agent_task_tool import create_scheduled_agent_task_tool
        scheduled_agent_task_tool = create_scheduled_agent_task_tool(profile=profile)
        tools.append(scheduled_agent_task_tool)
        tool_map["scheduled_agent_tasks.create_from_prompt"] = scheduled_agent_task_tool
        factory.logger.info("   ✅ Added create_scheduled_agent_task_from_prompt tool")
    except Exception as e:
        err = f"Failed to add scheduled agent task tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add web search tool for internet searches and current information
    try:
        from ....tools.external_services.web_search_tool import create_web_search_tool
        web_search_tool = create_web_search_tool(profile=profile)
        tools.append(web_search_tool)
        tool_map["web.search"] = web_search_tool
        factory.logger.info("   ✅ Added web_search tool (enables internet access)")
    except Exception as e:
        err = f"Failed to add web search tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add provider_catalog: discovery, authorization, and bounded dispatch for
    # attended ACP profiles and authorized workspace candidates. A resumed
    # delegated parent receives a bounded child outcome and must not create a
    # second provider delegation in the same request.
    if should_register_provider_catalog(factory):
        try:
            from ....tools.internal_basil_tools.provider_catalog_tool import (
                create_provider_catalog_tool,
            )
            provider_catalog_tool = create_provider_catalog_tool(
                profile=profile,
                agent_task_id=getattr(factory, "current_agent_task_id", None),
                root_task_id=getattr(factory, "current_root_task_id", None),
                submission_service=getattr(factory, "agent_task_submission_service", None),
            )
            tools.append(provider_catalog_tool)
            tool_map["provider.catalog"] = provider_catalog_tool
            factory.logger.info("   ✅ Added provider_catalog tool (registered ACP providers)")
        except Exception as e:
            err = f"Failed to add provider_catalog tool: {e}"
            optional_warnings.append(err)
            factory.logger.warning(f"   ⚠️ {err}")
    else:
        factory.logger.info(
            "   ⏭️ Skipped provider_catalog for delegated-provider continuation"
        )

    if should_register_delegated_agent(factory):
        try:
            from ....tools.internal_basil_tools.delegated_agent_tool import (
                create_delegated_agent_tool,
            )

            delegated_agent_tool = create_delegated_agent_tool(
                agent_task_id=getattr(factory, "current_agent_task_id", None),
                root_task_id=getattr(factory, "current_root_task_id", None),
                submission_service=getattr(factory, "agent_task_submission_service", None),
            )
            tools.append(delegated_agent_tool)
            tool_map["delegation.internal"] = delegated_agent_tool
            factory.logger.info("   ✅ Added delegated_agent tool (bounded internal children)")
        except Exception as e:
            err = f"Failed to add delegated_agent tool: {e}"
            optional_warnings.append(err)
            factory.logger.warning(f"   ⚠️ {err}")
    else:
        factory.logger.info("   ⏭️ Skipped delegated_agent for constrained child AgentTask")

    # Add external_catalog tool: single agent surface for all remote MCP
    # connectors the user has registered (Linear, GitHub, etc.). Discovers
    # connections + tools at runtime so adding a connection requires no
    # tool-registration change.
    try:
        from ....tools.external_services.external_catalog_tool import (
            create_external_catalog_tool,
        )
        external_catalog_tool = create_external_catalog_tool(profile=profile)
        tools.append(external_catalog_tool)
        tool_map["external.catalog"] = external_catalog_tool
        factory.logger.info("   ✅ Added external_catalog tool (remote MCP connectors)")
    except Exception as e:
        err = f"Failed to add external_catalog tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add browser inspection tool for DOM-aware web automation
    try:
        from ....tools.direct_application_interactions.browser_automation.browser_inspect_tool import create_browser_inspect_tool
        browser_inspect_tool = create_browser_inspect_tool(profile=profile)
        tools.append(browser_inspect_tool)
        tool_map["browser.inspect"] = browser_inspect_tool
        factory.logger.info("   ✅ Added browser_inspect tool")
    except Exception as e:
        err = f"Failed to add browser inspect tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add browser interaction tool for clicking, filling, navigating
    try:
        from ....tools.direct_application_interactions.browser_automation.browser_interact_tool import create_browser_interact_tool
        browser_interact_tool = create_browser_interact_tool(profile=profile)
        tools.append(browser_interact_tool)
        tool_map["browser.interact"] = browser_interact_tool
        factory.logger.info("   ✅ Added browser_interact tool")
    except Exception as e:
        err = f"Failed to add browser interact tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add browser target highlighting for visible action previews
    try:
        from ....tools.direct_application_interactions.browser_automation.browser_highlight_tool import create_browser_highlight_tool
        browser_highlight_tool = create_browser_highlight_tool(profile=profile)
        tools.append(browser_highlight_tool)
        tool_map["browser.highlight"] = browser_highlight_tool
        factory.logger.info("   ✅ Added browser_highlight tool")
    except Exception as e:
        err = f"Failed to add browser highlight tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add browser tab management tool for browser UI state
    try:
        from ....tools.direct_application_interactions.browser_automation.browser_tabs_tool import create_browser_tabs_tool
        browser_tabs_tool = create_browser_tabs_tool(profile=profile)
        tools.append(browser_tabs_tool)
        tool_map["browser.tabs"] = browser_tabs_tool
        factory.logger.info("   ✅ Added browser_tabs tool")
    except Exception as e:
        err = f"Failed to add browser tabs tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")

    # Add browser screenshot tool for vision fallback workflows
    try:
        from ....tools.direct_application_interactions.browser_automation.browser_screenshot_tool import create_browser_screenshot_tool
        browser_screenshot_tool = create_browser_screenshot_tool(profile=profile)
        tools.append(browser_screenshot_tool)
        tool_map["browser.screenshot"] = browser_screenshot_tool
        factory.logger.info("   ✅ Added browser_screenshot tool")
    except Exception as e:
        err = f"Failed to add browser screenshot tool: {e}"
        optional_warnings.append(err)
        factory.logger.warning(f"   ⚠️ {err}")
