"""The in-memory job registry: progress, one running job at a time, cancel, failures and expiry."""

import asyncio

import pytest

from api.services.memory.context_import.jobs import (
    JOB_TTL_SECONDS,
    STAGE_COMBINING,
    STAGE_LOADING,
    STAGE_READING,
    STAGE_WRITING,
    ImportBusyError,
    ImportJobs,
    UnknownJobError,
    stage_for_message,
)
from api.services.memory.context_import.models import ImportEmptyError
from api.services.memory.context_import.structuring import ImportCanceledError, ImportModelError


@pytest.mark.asyncio
async def test_a_job_runs_to_done_with_its_result_and_progress():
    jobs = ImportJobs()

    async def runner(job):
        job.report(1, 2, "Read part 1 of 2.")
        return {"ok": True}

    job = jobs.start("records", "me.md", 2, runner)
    await job.task

    payload = jobs.get(job.job_id).payload()
    assert payload["state"] == "done"
    assert payload["result"] == {"ok": True}
    assert (payload["chunks_done"], payload["chunks_total"]) == (1, 2)


@pytest.mark.asyncio
async def test_only_one_job_runs_at_a_time():
    jobs = ImportJobs()
    release = asyncio.Event()

    async def slow(job):
        await release.wait()
        return {}

    first = jobs.start("records", "a", 1, slow)
    with pytest.raises(ImportBusyError, match="still reading"):
        jobs.start("profile", "b", 1, slow)
    release.set()
    await first.task
    second = jobs.start("profile", "b", 1, slow)
    await second.task
    assert second.state == "done"


@pytest.mark.asyncio
async def test_cancel_is_seen_by_the_running_job():
    jobs = ImportJobs()
    started = asyncio.Event()

    async def runner(job):
        started.set()
        while not job.is_canceled():
            await asyncio.sleep(0.001)
        raise ImportCanceledError()

    job = jobs.start("records", "a", 1, runner)
    await started.wait()
    jobs.cancel(job.job_id)
    await job.task

    assert job.state == "canceled"
    assert "Nothing was saved" in job.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ImportEmptyError("Nothing here."), "Nothing here."),
        (ImportModelError("The model stopped."), "The model stopped."),
        (RuntimeError("boom"), "The import stopped unexpectedly. Nothing was saved."),
    ],
)
async def test_failures_carry_a_plain_message(error, expected):
    jobs = ImportJobs()

    async def runner(job):
        raise error

    job = jobs.start("records", "a", 1, runner)
    await job.task

    assert job.state == "failed"
    assert job.error == expected


def test_an_unknown_job_is_a_clear_error():
    with pytest.raises(UnknownJobError, match="no longer available"):
        ImportJobs().get("job-missing")


@pytest.mark.asyncio
async def test_finished_jobs_expire_after_an_hour():
    now = {"value": 0.0}
    jobs = ImportJobs(clock=lambda: now["value"])

    async def runner(job):
        return {}

    job = jobs.start("records", "a", 1, runner)
    await job.task
    now["value"] = JOB_TTL_SECONDS + 1

    with pytest.raises(UnknownJobError):
        jobs.get(job.job_id)


@pytest.mark.asyncio
async def test_only_the_most_recent_finished_jobs_are_kept():
    ticks = iter(range(1000))
    jobs = ImportJobs(clock=lambda: next(ticks))

    async def runner(job):
        return {}

    started = []
    for _ in range(10):
        job = jobs.start("records", "a", 1, runner)
        await job.task
        started.append(job)

    with pytest.raises(UnknownJobError):
        jobs.get(started[0].job_id)
    assert jobs.get(started[-1].job_id).state == "done"


@pytest.mark.asyncio
async def test_a_new_job_starts_in_the_loading_stage_and_follows_the_reader_messages():
    jobs = ImportJobs()
    seen = []

    async def runner(job):
        seen.append(job.payload()["stage"])
        job.report(0, 1, "Reading part 1 of 1.")
        seen.append(job.payload()["stage"])
        job.report(1, 1, "Read part 1 of 1.")
        job.report(1, 1, "Combining what I learned.")
        seen.append(job.payload()["stage"])
        job.report(1, 1, "Writing your profile.")
        seen.append(job.payload()["stage"])
        return {}

    job = jobs.start("profile", "me.md", 1, runner)
    await job.task

    assert seen == [STAGE_LOADING, STAGE_READING, STAGE_COMBINING, STAGE_WRITING]


def test_an_unknown_message_keeps_the_current_stage():
    assert stage_for_message("Stopping.", STAGE_READING) == STAGE_READING
    assert stage_for_message("Getting the model ready.", STAGE_LOADING) == STAGE_LOADING


@pytest.mark.asyncio
async def test_tokens_written_add_up_across_answers_even_though_each_answer_counts_from_zero():
    jobs = ImportJobs()

    async def runner(job):
        for count in (100, 400, 900):
            job.note_activity(count)
        job.note_activity(50)
        job.note_activity(250)
        return {}

    job = jobs.start("profile", "me.md", 1, runner)
    await job.task

    assert job.payload()["tokens_written"] == 900 + 250


def test_thinking_drops_think_tags_and_keeps_short_text_whole():
    from api.services.memory.context_import.jobs import thinking_for_display

    assert thinking_for_display("<think>The note says Boston.</think>\n{") == "The note says Boston.\n{"
    assert thinking_for_display("   ") == ""


def test_thinking_keeps_only_the_latest_stretch_and_never_starts_mid_word():
    from api.services.memory.context_import.jobs import MAX_THINKING_CHARS, thinking_for_display

    text = "alpha " * 1000

    shown = thinking_for_display(text)

    assert len(shown) <= MAX_THINKING_CHARS
    assert shown.startswith("alpha")
    assert shown == shown.strip()
    assert thinking_for_display("x" * (MAX_THINKING_CHARS + 50)) == "x" * MAX_THINKING_CHARS


@pytest.mark.asyncio
async def test_a_job_payload_carries_the_latest_thinking_and_the_next_answer_replaces_it():
    jobs = ImportJobs()

    async def runner(job):
        job.note_thinking("First, the role.")
        job.note_thinking("First, the role. Then the date style.")
        return {}

    job = jobs.start("profile", "me.md", 1, runner)
    await job.task
    assert job.payload()["thinking"] == "First, the role. Then the date style."

    job.note_thinking("A new answer.")
    assert job.payload()["thinking"] == "A new answer."
