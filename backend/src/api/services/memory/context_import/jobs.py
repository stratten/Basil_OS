"""In-memory registry of running imports, so a long read can show progress and be canceled."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from .models import ImportEmptyError
from .structuring import ImportCanceledError, ImportModelError

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 3600
MAX_KEPT_JOBS = 8

STAGE_LOADING = "loading"
STAGE_READING = "reading"
STAGE_COMBINING = "combining"
STAGE_WRITING = "writing"

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELED = "canceled"


class UnknownJobError(LookupError):
    """No import job has that id. It may have expired, or the backend restarted."""


class ImportBusyError(RuntimeError):
    """Another import is still reading."""


@dataclass
class ImportJob:
    job_id: str
    kind: str
    label: str
    chunks_total: int
    created: float
    state: str = STATE_RUNNING
    chunks_done: int = 0
    message: str = "Starting."
    stage: str = STAGE_LOADING
    # Tokens the model has written across every answer of this import, an estimate of how much work it has done. Each answer's count starts again at zero, so a lower value than the last one means a new answer began.
    tokens_written: int = 0
    _last_answer_tokens: int = field(default=0, repr=False)
    # The latest stretch of what a local model is writing, shown live. Empty for a cloud model, which does not stream here.
    thinking: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cancel_requested: bool = False
    task: Optional["asyncio.Task[None]"] = field(default=None, repr=False)

    def is_canceled(self) -> bool:
        return self.cancel_requested

    def report(self, done: int, total: int, message: str) -> None:
        self.chunks_done = done
        self.chunks_total = total
        self.message = message
        self.stage = stage_for_message(message, self.stage)

    def set_stage(self, stage: str, message: str) -> None:
        self.stage = stage
        self.message = message

    def note_activity(self, answer_tokens: int) -> None:
        """The model has written ``answer_tokens`` so far in its current answer."""
        if answer_tokens < self._last_answer_tokens:
            self._last_answer_tokens = 0
        self.tokens_written += answer_tokens - self._last_answer_tokens
        self._last_answer_tokens = answer_tokens

    def note_thinking(self, streamed_tail: str) -> None:
        """The model has streamed ``streamed_tail`` (the end of its current answer) so far."""
        self.thinking = thinking_for_display(streamed_tail)

    def payload(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "label": self.label,
            "state": self.state,
            "chunks_done": self.chunks_done,
            "chunks_total": self.chunks_total,
            "message": self.message,
            "stage": self.stage,
            "tokens_written": self.tokens_written,
            "thinking": self.thinking,
            "result": self.result,
            "error": self.error,
        }


MAX_THINKING_CHARS = 1500
_THINK_TAG = re.compile(r"</?think>", re.IGNORECASE)


def thinking_for_display(streamed_tail: str) -> str:
    """The streamed text without think tags, cut to its last ``MAX_THINKING_CHARS`` characters and starting at a whole word so the cut never shows half a word."""
    text = _THINK_TAG.sub("", streamed_tail).strip()
    if len(text) <= MAX_THINKING_CHARS:
        return text
    tail = text[-MAX_THINKING_CHARS:]
    first_break = re.search(r"\s", tail)
    return tail[first_break.end():].lstrip() if first_break else tail


def stage_for_message(message: str, current: str) -> str:
    """The stage a progress message belongs to. Messages from the readers are fixed phrases, so the stage follows them without changing the callback every reader shares."""
    if message.startswith(("Reading part", "Read part")):
        return STAGE_READING
    if message.startswith("Combining"):
        return STAGE_COMBINING
    if message.startswith("Writing"):
        return STAGE_WRITING
    return current


Runner = Callable[[ImportJob], Awaitable[Dict[str, Any]]]


class ImportJobs:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._jobs: Dict[str, ImportJob] = {}

    def start(self, kind: str, label: str, chunks_total: int, runner: Runner) -> ImportJob:
        self._evict()
        if any(job.state == STATE_RUNNING for job in self._jobs.values()):
            raise ImportBusyError("Another import is still reading. Wait for it to finish, or cancel it first.")
        job = ImportJob(job_id=f"job-{uuid.uuid4().hex[:12]}", kind=kind, label=label, chunks_total=chunks_total, created=self._clock())
        self._jobs[job.job_id] = job
        job.task = asyncio.get_running_loop().create_task(self._run(job, runner))
        return job

    def get(self, job_id: str) -> ImportJob:
        self._evict()
        job = self._jobs.get(job_id)
        if job is None:
            raise UnknownJobError("This import is no longer available. Start it again.")
        return job

    def cancel(self, job_id: str) -> ImportJob:
        job = self.get(job_id)
        if job.state == STATE_RUNNING:
            job.cancel_requested = True
            job.message = "Stopping."
        return job

    async def _run(self, job: ImportJob, runner: Runner) -> None:
        try:
            job.result = await runner(job)
            job.state = STATE_DONE
            job.message = "Finished."
        except ImportCanceledError:
            job.state = STATE_CANCELED
            job.message = "Canceled. Nothing was saved."
        except (ImportEmptyError, ImportModelError) as exc:
            job.state = STATE_FAILED
            job.error = str(exc)
            job.message = str(exc)
        except Exception as exc:
            logger.error("Context import job %s failed: %s", job.job_id, exc, exc_info=True)
            job.state = STATE_FAILED
            job.error = "The import stopped unexpectedly. Nothing was saved."
            job.message = job.error

    def _evict(self) -> None:
        now = self._clock()
        expired = [key for key, job in self._jobs.items() if job.state != STATE_RUNNING and now - job.created > JOB_TTL_SECONDS]
        for key in expired:
            self._jobs.pop(key, None)
        finished = [job for job in self._jobs.values() if job.state != STATE_RUNNING]
        for job in sorted(finished, key=lambda entry: entry.created)[: max(0, len(finished) - MAX_KEPT_JOBS)]:
            self._jobs.pop(job.job_id, None)

