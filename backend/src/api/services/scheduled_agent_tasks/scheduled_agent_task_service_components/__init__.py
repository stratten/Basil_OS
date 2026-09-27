"""Internal component modules for ``ScheduledAgentTaskService``.

This package is an implementation detail of
``api.services.scheduled_agent_tasks.scheduled_agent_task_service``. Public consumers
of the scheduled-agent-tasks feature should import from
``api.services.scheduled_agent_tasks`` (or its facade module), not from here.

The split exists so the facade stays narrow and each component has a single
responsibility:

* ``schedule_time_math``       -- pure time/timezone helpers and next-run math.
* ``schedule_interpretation``  -- LLM-driven natural-language interpretation,
                                  including the multi-turn clarification thread
                                  store (process-singleton module-level state).
* ``scheduled_run_lifecycle``  -- create/update/enqueue/recover/finalize
                                  workflows around scheduled agent task rows and
                                  their run rows.
* ``scheduled_run_execution``  -- driving an individual queued run to completion
                                  via the voice listener service, including the
                                  agent_task terminal-status -> asyncio.Future
                                  bridge (also process-singleton module-level
                                  state).
* ``scheduled_agent_task_runtime``-- FastAPI-startup wiring that stitches the
                                  pieces together.
"""
