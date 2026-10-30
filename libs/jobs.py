import logging
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)

_MAX_JOBS = 50


class JobCancelled(Exception):
    """The job was interrupted on purpose, so it must not be retried or reported as an error."""


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued, prompt, waiting, rendering, done, failed, cancelled
    prompt: str = ""
    model: str = ""
    error: str = ""
    created: float = field(default_factory=time.time)
    finished: float | None = None


_jobs: OrderedDict[str, Job] = OrderedDict()
_lock = threading.Lock()
_current = threading.local()
_executor = ThreadPoolExecutor(max_workers=2)


def _new_job(**fields) -> Job:
    job = Job(id=uuid.uuid4().hex, **fields)
    with _lock:
        _jobs[job.id] = job
        while len(_jobs) > _MAX_JOBS:
            _jobs.popitem(last=False)
    return job


def _finish(job: Job, status: str, error: str = "") -> None:
    with _lock:
        job.status = status
        job.error = error
        job.finished = time.time()


def _run(job: Job, fn, args) -> None:
    _current.job = job
    try:
        fn(*args)
        _finish(job, "done")
    except JobCancelled:
        _finish(job, "cancelled")
    except Exception as e:
        logger.exception("Job %s failed", job.id)
        _finish(job, "failed", str(e))
    finally:
        _current.job = None


def submit(fn, *args, **fields) -> str:
    """Runs fn on a worker thread and returns the job id. fields set the initial Job values."""
    job = _new_job(**fields)
    _executor.submit(_run, job, fn, args)
    return job.id


def run(fn, *args, **fields) -> str:
    """Runs fn on this thread with the same tracking as submit()."""
    job = _new_job(**fields)
    _run(job, fn, args)
    return job.id


def update_current(**fields) -> None:
    """Updates the job this thread is running. Does nothing outside a job."""
    job = getattr(_current, "job", None)
    if job is None:
        return
    with _lock:
        for name, value in fields.items():
            setattr(job, name, value)


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return asdict(job) if job else None
