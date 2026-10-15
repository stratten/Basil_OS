import httpx
import pytest
from fastapi import FastAPI

from api.routes.meetings import resource_advice_routes
from api.routes.meetings import router as meetings_router
from api.services.meeting_resources.advisor import ResourceAdvisor
from api.services.meeting_resources.models import ResourceSnapshot


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def make_advisor(clock, sent):
    async def broadcaster(message):
        sent.append(message)

    holder = {"snapshot": ResourceSnapshot(recording=True, lag_seconds=30.0)}
    advisor = ResourceAdvisor(lambda thermal: holder["snapshot"], broadcaster=broadcaster, clock=clock, wall_clock=lambda: 9000.0, sustain_seconds=10, clear_seconds=10)
    return advisor


def client_for(advisor):
    app = FastAPI()
    app.dependency_overrides[resource_advice_routes.get_advisor] = lambda: advisor
    app.include_router(meetings_router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def raised_advisor():
    clock, sent = Clock(), []
    advisor = make_advisor(clock, sent)
    advisor.sample()
    clock.now = 10.0
    advisor.sample()
    return advisor, sent


@pytest.mark.asyncio
async def test_routes_are_registered_before_the_lifecycle_catch_all():
    advisor, _ = raised_advisor()
    async with client_for(advisor) as client:
        response = await client.get("/meetings/resource-advice")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"revision", "advice"} and body["advice"][0]["id"] == "transcription_lag"
    assert set(body["advice"][0]) == {"id", "severity", "title", "detail", "action", "raised_at"}


@pytest.mark.asyncio
async def test_thermal_report_is_validated_and_recorded():
    advisor, _ = raised_advisor()
    async with client_for(advisor) as client:
        good = await client.put("/meetings/resource-advice/client-state", json={"thermal_state": "serious"})
        bad = await client.put("/meetings/resource-advice/client-state", json={"thermal_state": "lava"})
        extra = await client.put("/meetings/resource-advice/client-state", json={"thermal_state": "fair", "other": 1})
        empty = await client.put("/meetings/resource-advice/client-state", json={})
    assert good.status_code == 200 and bad.status_code == 422 and extra.status_code == 422 and empty.status_code == 422
    assert advisor._fresh_thermal_state(advisor._clock()) == "serious"


@pytest.mark.asyncio
async def test_dismiss_hides_the_advice_broadcasts_and_rejects_unknown_ids():
    advisor, sent = raised_advisor()
    async with client_for(advisor) as client:
        missing = await client.post("/meetings/resource-advice/not-showing/dismiss")
        dismissed = await client.post("/meetings/resource-advice/transcription_lag/dismiss")
        again = await client.post("/meetings/resource-advice/transcription_lag/dismiss")
    assert missing.status_code == 404 and again.status_code == 200
    assert dismissed.status_code == 200 and dismissed.json()["advice"] == []
    assert sent[-1]["event_type"] == "resource_advice" and sent[-1]["advice"] == []


@pytest.mark.asyncio
async def test_routes_answer_503_when_the_advisor_is_not_running(monkeypatch):
    monkeypatch.setattr(resource_advice_routes, "get_resource_advisor", lambda: None)
    app = FastAPI()
    app.include_router(meetings_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/meetings/resource-advice")).status_code == 503
        assert (await client.put("/meetings/resource-advice/client-state", json={"thermal_state": "fair"})).status_code == 503
        assert (await client.post("/meetings/resource-advice/x/dismiss")).status_code == 503
