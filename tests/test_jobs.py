import pytest

from libs import jobs


def wait_for(job_id):
    jobs._executor.submit(lambda: None).result()
    for _ in range(200):
        job = jobs.get_job(job_id)
        if job["finished"]:
            return job
        import time
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_successful_job():
    job = jobs.get_job(jobs.run(lambda: None, prompt="a cat"))
    assert job["status"] == "done"
    assert job["prompt"] == "a cat"
    assert job["finished"] is not None


def test_failed_job_records_the_error():
    def boom():
        raise RuntimeError("no gpu")

    job = jobs.get_job(jobs.run(boom))
    assert job["status"] == "failed"
    assert job["error"] == "no gpu"


def test_cancelled_job_is_not_an_error():
    def cancel():
        raise jobs.JobCancelled()

    job = jobs.get_job(jobs.run(cancel))
    assert job["status"] == "cancelled"
    assert job["error"] == ""


def test_submit_tracks_updates_from_the_worker():
    def work():
        jobs.update_current(status="rendering", model="sdxl")

    job = wait_for(jobs.submit(work))
    assert job["status"] == "done"
    assert job["model"] == "sdxl"


def test_update_outside_a_job_is_ignored():
    jobs.update_current(status="rendering")


def test_old_jobs_are_dropped(monkeypatch):
    monkeypatch.setattr(jobs, "_MAX_JOBS", 2)
    first = jobs.run(lambda: None)
    jobs.run(lambda: None)
    jobs.run(lambda: None)
    assert jobs.get_job(first) is None


@pytest.mark.parametrize("job_id", ["", "missing"])
def test_unknown_job(job_id):
    assert jobs.get_job(job_id) is None
