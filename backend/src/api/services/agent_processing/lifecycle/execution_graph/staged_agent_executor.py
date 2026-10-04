"""AgentExecutor that ends a staged pass whenever a step newly loads tool families."""

from __future__ import annotations

import json
from typing import Any, Sequence

from langchain_classic.agents import AgentExecutor
from langchain_core.agents import AgentAction, AgentFinish

LOAD_TOOL_FAMILY_TOOL_NAME = "load_tool_family"


def batched_family_load_observation(steps: Sequence[Any]) -> Any | None:
    """Return the loader observation when a multi-call step newly loaded tool families.

    LangChain honors ``return_direct`` only for single-call steps, so a ``load_tool_family`` call batched with other tool calls would otherwise leave the pass running without the newly loaded tools bound.
    """
    if len(steps) < 2:
        return None
    for step in steps:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        if getattr(action, "tool", None) != LOAD_TOOL_FAMILY_TOOL_NAME:
            continue
        payload = observation
        if isinstance(observation, str):
            try:
                payload = json.loads(observation)
            except ValueError:
                continue
        if isinstance(payload, dict) and payload.get("newly_loaded_families"):
            return observation
    return None


class StagedAgentExecutor(AgentExecutor):
    """Ends the pass after a batched step that newly loads families, like single-call ``return_direct``."""

    def _finish_after_batched_family_load(
        self,
        next_step_output: AgentFinish | list[tuple[AgentAction, str]],
        intermediate_steps: list[tuple[AgentAction, str]],
    ) -> AgentFinish | list[tuple[AgentAction, str]]:
        if isinstance(next_step_output, AgentFinish):
            return next_step_output
        observation = batched_family_load_observation(next_step_output)
        if observation is None:
            return next_step_output
        # The caller only extends intermediate_steps for list results, so record this step's completed calls before finishing.
        intermediate_steps.extend(next_step_output)
        return_value_key = self._action_agent.return_values[0] if self._action_agent.return_values else "output"
        return AgentFinish({return_value_key: observation}, "")

    def _take_next_step(
        self,
        name_to_tool_map,
        color_mapping,
        inputs,
        intermediate_steps,
        run_manager=None,
    ):
        next_step_output = super()._take_next_step(
            name_to_tool_map,
            color_mapping,
            inputs,
            intermediate_steps,
            run_manager=run_manager,
        )
        return self._finish_after_batched_family_load(next_step_output, intermediate_steps)

    async def _atake_next_step(
        self,
        name_to_tool_map,
        color_mapping,
        inputs,
        intermediate_steps,
        run_manager=None,
    ):
        next_step_output = await super()._atake_next_step(
            name_to_tool_map,
            color_mapping,
            inputs,
            intermediate_steps,
            run_manager=run_manager,
        )
        return self._finish_after_batched_family_load(next_step_output, intermediate_steps)
