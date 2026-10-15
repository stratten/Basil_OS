import pytest


@pytest.mark.asyncio
async def test_live_statuses_lists_every_live_session(runtime_factory, recorder_factory):
    env = runtime_factory()
    assert env.runtime.live_statuses() == []
    env.recorders.append(recorder_factory("mic1"))
    await env.runtime.enable("mic1")
    statuses = env.runtime.live_statuses()
    assert len(statuses) == 1 and statuses[0].live is True and statuses[0].enabled is True and statuses[0].capacity == "ok"
    await env.runtime.shutdown()
    assert env.runtime.live_statuses() == []
