# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The two decisions of socat_points_worker that exist nowhere else and fail silently: a killed run with
committed progress RESUMES (no 7-day back-off), and a run that dies twice at the same cruise does not retry
that cruise for ever."""
import socat_points_worker as w
from socat_helpers import conn, db, needs_db  # noqa: F401  (fixtures)

SHA = "a" * 64


async def _killed_run_with_progress(conn, expocode="06AQ20200801"):
    """What the loader leaves after a run that committed batches up to `expocode` and then died."""
    await conn.execute(
        "UPDATE socat_points_source SET loaded_at = now(), staging_sha256 = $1, staging_last_expocode = $2, "
        "staging_rows = 10", SHA, expocode)


@needs_db
async def test_interrupted_with_progress_resumes(db):
    await _killed_run_with_progress(db)
    assert await w._stamp_start(db) == 1                # the run that was then killed stamped it
    assert await db.fetchval("SELECT last_failure FROM socat_points_source") == "interrupted"
    assert await w._decide(db, head=lambda: {}, current_sha=SHA) == "resume"
    # staging that belongs to ANOTHER file is not resumed: that is a plain back-off
    assert await w._decide(db, head=lambda: {}, current_sha="b" * 64) == "backoff"


@needs_db
async def test_interrupted_twice_same_cruise_backs_off(db):
    await _killed_run_with_progress(db)
    assert await w._stamp_start(db) == 1
    assert await w._decide(db, head=lambda: {}, current_sha=SHA) == "resume"
    # the resumed run was killed too, before committing a batch past the same expocode
    assert await w._stamp_start(db) == 2
    assert await w._decide(db, head=lambda: {}, current_sha=SHA) == "backoff"
    # progress past the stamped cruise starts the count again
    await db.execute("UPDATE socat_points_source SET staging_last_expocode = '11BE20021104'")
    assert await w._stamp_start(db) == 1
    assert await w._decide(db, head=lambda: {}, current_sha=SHA) == "resume"


@needs_db
async def test_expired_backoff_drops_exhausted_staging_instead_of_backing_off_forever(db):
    """After 7 days the back-off lapses, but the staging that died twice at one cruise is still there with count 2:
    the next stamp would count 3 and back off (and alert) again, for ever."""
    await _killed_run_with_progress(db)
    await db.execute("UPDATE socat_points_source SET loaded_at = NULL, last_failure = 'interrupted', "
                     "interrupted_expocode = staging_last_expocode, interrupt_count = 2, "
                     "last_failed_at = now() - interval '8 days'")
    assert await w._decide(db, head=lambda: {}, current_sha=SHA) == "never"      # the window has lapsed
    assert await w._drop_exhausted_staging(db) is True
    assert await w._stamp_start(db) == 0                                          # a fresh start, not count 3
    row = await db.fetchrow("SELECT staging_sha256, staging_last_expocode FROM socat_points_source")
    assert row["staging_sha256"] is None and row["staging_last_expocode"] is None


@needs_db
async def test_requested_after_one_killed_run_starts_fresh_and_does_not_back_off(db):
    """One killed run (count 1), then an operator request: the new attempt must not count as the second
    interruption at the same cruise (alert + back-off, nothing run, request consumed)."""
    await _killed_run_with_progress(db)
    assert await w._stamp_start(db) == 1                                   # the killed run
    await db.execute("UPDATE socat_points_source SET refresh_requested_at = now() + interval '1 second'")
    assert await w._decide(db, head=lambda: {}, current_sha=SHA) == "requested"
    await w._drop_exhausted_staging(db)                                    # what _run does for a non-resume decision
    assert await w._stamp_start(db) == 0                                   # fresh start: below the cap


@needs_db
async def test_lock_timeout_leaves_a_resume_and_keeps_the_staging(db):
    """A complete staging whose swap lost the lock race: the next run resumes it (swap retry), it does not
    back off, and the non-resume clean-up must not be what the next decision leads to."""
    await _killed_run_with_progress(db)
    assert await w._stamp_start(db) == 1                       # the run that staged everything
    await w._stamp_outcome(db, "lock_timeout")
    assert await db.fetchval("SELECT interrupt_count FROM socat_points_source") is None
    assert await w._decide(db, head=lambda: {}, current_sha=SHA) == "resume"
    # a few days later, still a resume (no 7-day window); the staging is intact
    await db.execute("UPDATE socat_points_source SET last_failed_at = now() - interval '30 days'")
    assert await w._decide(db, head=lambda: {}, current_sha=SHA) == "resume"
    assert await db.fetchval("SELECT staging_sha256 FROM socat_points_source") == SHA
    # a different file meanwhile: a fresh import is correct, not a resume
    assert await w._decide(db, head=lambda: {}, current_sha="b" * 64) != "resume"
