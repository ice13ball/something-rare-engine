# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Our ONC archive collects; it must never compute.

Michal's rule, 2026-09-10: this portal mirrors its sources 1:1. Collecting what
a source publishes over time is not a modification — but the moment we average,
interpolate or fill anything ourselves, it becomes one. This suite holds that
line.

Why the archive exists at all. ONC caps a scalardata response at 100,000
samples per property. Measured against BACAX the same day:

    7 days of the raw 1 Hz stream   -> 100,000 samples covering 1.2 days
                                       (the other 5.8 dropped silently)
    7 days at resamplePeriod=600    ->   1,009 samples covering all 7 days

So the resampled series is not a lesser product — it is the only one that comes
back complete. And it is still ONC's: THEY compute the average, by their
method, and their `counts` travels with it so the number of raw samples behind
each bin is disclosed rather than hidden.

Nine properties arrive in that one response — conductivity, density, depth,
pressure, salinity, sigmat, sigmatheta, soundspeed, seawatertemperature — and
only three were being kept.
"""
import ast
import math
import pathlib
import re
import sys

ROOT   = pathlib.Path(__file__).resolve().parents[1]
ONC    = ROOT / "domains" / "onc.py"
SCHEMA = ROOT / "schema" / "onc.py"
MAIN   = ROOT / "main.py"

_SRC = ONC.read_text(encoding="utf-8")


def _sync_body() -> str:
    i = _SRC.index("async def sync_onc_ctd_series")
    return _SRC[i:_SRC.index("\n# ── USGS Earthquakes", i)]


def _sync_code() -> str:
    """The sync with comments and docstrings stripped.

    ⛔ Three guards in three days first reddened on the assistant's own prose:
    a counter test tripped on a comment quoting the forbidden pattern, a unit
    test on a comment quoting the old contract, and this one on the sentence
    "Nothing is ever deleted here". A rule about what the CODE does has to be
    checked against the code.
    """
    tree = ast.parse(_sync_body())
    docstrings = {id(n.value) for n in ast.walk(tree)
                  if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                  and isinstance(n.value.value, str)}
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                out.append(node.value)      # real string literals, incl. SQL
        elif isinstance(node, (ast.Call, ast.Attribute, ast.Name)):
            out.append(ast.unparse(node))
    return "\n".join(out)


def test_the_fixture_isolated_the_sync():
    body = _sync_body()
    assert "onc_ctd_series" in body and len(body) > 1500, (
        "fixture problem: sync_onc_ctd_series did not slice out"
    )


def test_the_average_is_asked_for_not_computed():
    # ⛔ The whole justification. If we ever compute the mean ourselves, this
    # stops being an archive of ONC's data and becomes a product of our own.
    body = _sync_body()
    assert '"resampleType":       "avg"' in body or '"resampleType": "avg"' in body, (
        "the sync no longer asks ONC to do the averaging"
    )
    assert "_ONC_SERIES_RESAMPLE_S" in body, "the cadence is not a named constant"
    for forbidden in ("statistics.mean", "np.mean", "sum(values)", "/ len(values)"):
        assert forbidden not in body, (
            f"{forbidden!r} appears in the archive sync — we are computing a "
            "value ONC did not publish"
        )


def test_oncs_own_bin_figures_are_kept():
    # counts is what makes an average readable rather than a bare number: it
    # says how many raw samples ONC put behind it.
    body = _sync_body()
    for key in ('data.get("counts")', 'data.get("qaqcFlags")'):
        assert key in body, f"{key} is fetched by ONC and thrown away"
    ddl = SCHEMA.read_text(encoding="utf-8")
    for col in ("raw_count", "qaqc_flag", "value_min", "value_max", "resample_s"):
        assert col in ddl, f"onc_ctd_series has no column for {col}"


def test_every_property_onc_returns_is_stored_not_just_the_plotted_three():
    # ⛔ No allow-list of property names anywhere in the loop. The old profile
    # sync kept depth/temperature/salinity and dropped six others.
    # ⛔ The WHOLE sync, comments stripped — not just the loop. Scoping this to
    # the loop let a sabotage pass: an allow-list tuple declared three lines
    # above the loop is outside that slice and the guard never saw it.
    code = _sync_code()
    assert 'sensor.get' in code and 'propertyCode' in code, (
        "the sync no longer takes the property code from ONC's own response"
    )
    for name in ("conductivity", "density", "soundspeed", "sigmat",
                 "sigmatheta", "pressure", "salinity", "seawatertemperature",
                 "temperature", "depth"):
        assert name not in code, (
            f"the archive sync names the property {name!r}. A named property is "
            "a filter, and a filter drops what ONC published — the old profile "
            "sync kept three of the nine that arrive in every response."
        )


def test_nothing_in_the_archive_is_ever_deleted():
    # ⛔ Checked against the CODE, not the file text — the docstring above the
    # sync contains the sentence "Nothing is ever deleted here", and a plain
    # substring search reddens on it.
    code = _sync_code()
    assert len(code) > 500, "fixture problem: stripping produced almost nothing"
    assert "INSERT INTO onc_ctd_series" in code, (
        "fixture problem: SQL literals were stripped too, so a real DELETE "
        "would slip past this guard unnoticed"
    )
    for word in ("DELETE FROM", "TRUNCATE"):
        assert word not in code.upper(), (
            f"the archive sync runs {word}. It accumulates; pruning it would "
            "recreate exactly the hole this table exists to fill."
        )


def test_a_revised_bin_lands_and_an_unchanged_one_is_not_touched():
    body = _sync_body()
    ins = body[body.index("INSERT INTO onc_ctd_series"):]
    ins = ins[:ins.index('"""')]
    assert "DO UPDATE" in ins, (
        "DO NOTHING would freeze the first version of every bin, the same "
        "defect just fixed on onc_ctd_profiles"
    )
    assert "IS DISTINCT FROM EXCLUDED.value" in ins, (
        "an unchanged re-fetch rewrites the row, so updated_at stops meaning "
        "'when ONC changed this'"
    )


def test_the_deployment_citation_is_stored_because_it_is_an_obligation():
    body = _sync_body()
    assert 'payload.get("citations")' in body, (
        "ONC returns a DOI and a formatted citation per deployment and we drop "
        "them — a reader cannot cite the deployment their number came from"
    )
    assert "onc_deployment_citations" in SCHEMA.read_text(encoding="utf-8")


def test_the_token_never_reaches_a_log_line():
    # ⛔ ONC echoes the token in queryUrl and parameters.token. It leaked into a
    # transcript once already this week.
    body = _sync_body()
    for m in re.finditer(r"log\.(warning|error|info|exception)\((.*?)\)", body, re.S):
        text = m.group(2)
        assert "params" not in text and "url" not in text.lower(), (
            f"a log line carries the request: {text[:120]!r}"
        )


def test_the_sync_is_reachable_from_the_dashboard_and_from_startup():
    # ⛔ A sync nobody can trigger and nothing schedules is a sync that never
    # runs. Both admin registries, plus the scheduled task.
    #
    # 2026-09-18: the 43 scheduled tasks (this one included) moved out of
    # main.py's lifespan() into scheduling.TASK_REGISTRY as part of the
    # web/worker process split — lifespan() now starts them through one
    # generic loop over that registry, so "_onc_ctd_series_task()" and
    # "asyncio.create_task(_onc_ctd_series_task())" no longer appear
    # literally in main.py's source at all (that's not a regression: see
    # backend/tests/test_task_registry.py, which asserts lifespan() has
    # exactly one create_task call site precisely so a task CAN'T be wired
    # in by hand outside the registry any more). The reachability question
    # this test cares about — "is it wired to something that starts it" —
    # is answered by the registry now, not by grepping main.py.
    main_src = MAIN.read_text(encoding="utf-8")
    assert '"onc-ctd-series":         "onc-ctd-series",' in main_src, (
        "missing from _SOURCE_TO_ACTION — the Force Sync button silently does nothing"
    )
    # _SYNC_SOURCES itself moved to sync_sources.py on 2026-09-18 (the worker
    # must reach it without importing main); main.py re-exports the name, so
    # the literal to grep for now lives in the other file.
    sync_sources_src = (MAIN.parent / "sync_sources.py").read_text(encoding="utf-8")
    assert "onc.sync_onc_ctd_series()" in sync_sources_src, "missing from SYNC_SOURCES"

    import scheduling
    names = {t.name for t in scheduling.TASK_REGISTRY}
    assert "onc-ctd-series-archive" in names, "no registry entry creates it"
    worker_names = {t.name for t in scheduling.tasks_for_role("worker")}
    assert "onc-ctd-series-archive" in worker_names, (
        "the task exists in the registry but is not wired to a role that "
        "ever starts it"
    )


def test_the_schema_is_registered_so_the_table_exists_on_deploy():
    init = (ROOT / "schema" / "__init__.py").read_text(encoding="utf-8")
    assert "ensure_onc_ctd_series" in init, (
        "the table is defined but ensure_schema never creates it"
    )


def test_a_bin_onc_marks_as_empty_is_stored_as_absent_not_as_nan():
    """⛔ ONC sends a bare NaN for a bin with no data.

    Measured on BACAX 2026-09-10 over a 7-day resampled response: 18 of 9,081
    samples were NaN and EVERY ONE carried ONC's own flag 6, while all 9,063
    others carried flag 7 (averaged — a processing note, not an error). NULL is
    SQL's word for exactly what their flag already says, and it is what keeps
    the value out of a JSON body, where a bare NaN is not valid JSON and takes
    the client's .map() down with it. This platform has a documented engine
    rule about precisely that.
    """
    code = _sync_code()
    assert "math.isnan" in code, (
        "ONC's NaN reaches the column unchanged; the API will then emit invalid "
        "JSON and every client parsing the response throws"
    )
    # And the flag must survive, or "no data" and "we lost it" become the same.
    assert "qaqc_flag" in code or "qaqcFlags" in code, (
        "the value is nulled but ONC's reason for it is dropped"
    )


def test_no_column_exists_that_onc_never_fills():
    """A column at 100% NULL is the defect this whole audit keeps finding.

    The first draft of this table had value_min and value_max. A dry run against
    live ONC showed the resampled response carries counts, qaqcFlags, minTimes,
    maxTimes, minQuality and maxQuality — the TIMES of the extremes, never their
    values. Both columns would have been empty forever.
    """
    ddl = SCHEMA.read_text(encoding="utf-8")
    i = ddl.index("CREATE TABLE IF NOT EXISTS onc_ctd_series")
    table = ddl[i:ddl.index('"""', i)]
    # ⛔ Strip the `--` comments first. This is the FOURTH guard in one session
    # to redden on the assistant's own prose: a counter test on a comment
    # quoting the forbidden pattern, a units test on a comment quoting the old
    # contract, a delete test on the words "Nothing is ever deleted here", and
    # now this one on the comment that explains why value_min was removed.
    # A rule about what the SCHEMA declares must be read from the declaration.
    table = "\n".join(ln.split("--")[0] for ln in table.splitlines())
    assert "resample_s" in table, "fixture problem: comment-stripping ate the columns"
    for phantom in ("value_min", "value_max"):
        assert phantom not in table, (
            f"{phantom} is back. ONC does not publish it in the resampled "
            "response — the column would be 100% NULL forever."
        )
    # Every remaining column must be written by the sync.
    code = _sync_code()
    for col in ("value", "unit", "qaqc_flag", "raw_count", "resample_s"):
        assert col in code, f"column {col} exists but the sync never writes it"


def test_the_new_row_count_is_measured_once_not_per_device():
    """⛔ A concurrent before/after count double-counts.

    The first version of this sync took `SELECT count(*)` before and after the
    insert INSIDE each of the concurrent per-device tasks. The windows overlap,
    so every task counted rows its neighbours had just inserted. Production
    reported it plainly on the very first run:

        onc_ctd_series: 232,807 samples returned, 239,678 new rows,
                        231,798 in archive

    More arrivals than there were samples to arrive — the same shape of counter
    defect this audit corrected on ISA, on the acoustic stations and on ONC's
    own CTD profiles, written by me while correcting the fourth of them.
    """
    body = _sync_body()
    # ⛔ The nested function taken by AST, not by slicing to the next `async
    # with`. A text slice swallowed the whole-run count that deliberately sits
    # between _one and the gather, and reddened on the fix itself.
    tree = ast.parse(body)
    inner_fn = next(n for n in ast.walk(tree)
                    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and n.name == "_one")
    inner = ast.unparse(inner_fn)
    assert "executemany" in inner, "fixture problem: _one did not unparse"
    assert "SELECT count(*) FROM onc_ctd_series" not in inner, (
        "the per-device task counts the table again — under asyncio.gather "
        "those counts overlap and the total is meaningless"
    )
    # And it must still be counted somewhere, or the monitor is blind.
    outer = body[body.index("async with httpx.AsyncClient()"):]
    assert outer.count("SELECT count(*) FROM onc_ctd_series") >= 1, (
        "nothing counts the archive at all now"
    )
    assert "stored = in_table - before" in body, (
        "the new-row figure is no longer a difference of two whole-table counts"
    )
