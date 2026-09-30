"""
test_models.py
--------------
Tests for how models.py handles failures. Run with:  python -m pytest -q

No real API calls. We swap in a fake "Gemini" that fails on purpose, so we can
prove each failure is handled right without a key, without cost, and without waiting.
Several of these tests use the exact error text the live app got from Google.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models
import run_check

# The real message Google returned when the free daily allowance ran out.
REAL_DAILY_LIMIT_ERROR = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota. "
    "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
    "limit: 20, model: gemini-3.5-flash\\nPlease retry in 22.207691463s.', 'status': 'RESOURCE_EXHAUSTED', "
    "'details': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}, {'retryDelay': '22s'}]}}"
)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Make retry waits instant, record how long we would have waited, and reset state."""
    waits = []
    monkeypatch.setattr(models.time, "sleep", lambda s: waits.append(s))
    models.last_model_used.clear()
    models._exhausted_today.clear()
    return waits


def use_fake_gemini(monkeypatch, fake):
    monkeypatch.setitem(models.PROVIDERS, "gemini", ("gemini-3.5-flash", fake, "GEMINI_API_KEY"))


def test_daily_limit_moves_to_the_next_model_without_waiting(monkeypatch, no_waiting):
    """This is the error that broke the live app. One model out for the day, the next still has its own 20."""
    def fake(q, model, key):
        if model == "gemini-3.5-flash":
            raise Exception(REAL_DAILY_LIMIT_ERROR)
        return f"1. Goodthing Coffee - answered by {model}"

    use_fake_gemini(monkeypatch, fake)
    assert "gemini-3.5-flash-lite" in models.ask("gemini", "q", api_key="k")
    assert no_waiting == []                                     # no pointless 22s wait
    assert models.model_id("gemini") == "gemini-3.5-flash-lite"  # CSV records the real model


def test_exhausted_model_is_skipped_on_later_calls(monkeypatch):
    tried = []

    def fake(q, model, key):
        tried.append(model)
        if model == "gemini-3.5-flash":
            raise Exception(REAL_DAILY_LIMIT_ERROR)
        return "ok"

    use_fake_gemini(monkeypatch, fake)
    models.ask("gemini", "q1", api_key="k")
    models.last_model_used.clear()           # even forgetting the last model...
    models.ask("gemini", "q2", api_key="k")
    assert tried.count("gemini-3.5-flash") == 1   # ...we don't hit the empty one twice


def test_every_model_out_for_the_day_says_so_plainly(monkeypatch):
    def fake(q, model, key):
        raise Exception(REAL_DAILY_LIMIT_ERROR)

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.ModelError, match="resets at midnight Pacific"):
        models.ask("gemini", "q", api_key="k")


def test_per_minute_limit_waits_as_long_as_google_says(monkeypatch, no_waiting):
    calls = {"n": 0}

    def fake(q, model, key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("429 RESOURCE_EXHAUSTED: too many requests per minute. Please retry in 7.5s.")
        return "ok"

    use_fake_gemini(monkeypatch, fake)
    assert models.ask("gemini", "q", api_key="k") == "ok"
    assert no_waiting == [8.5]   # Google's number plus a 1 second cushion


def test_wait_time_containing_403_is_not_mistaken_for_a_bad_key():
    assert not models._is_auth_error("429 quota exceeded, please retry in 22.4031s")
    assert models._is_auth_error("403 Forbidden")


def test_bad_key_stops_immediately(monkeypatch, no_waiting):
    def fake(q, model, key):
        raise Exception("400 INVALID_ARGUMENT: API key not valid. Please pass a valid API key.")

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.ModelError, match="rejected the API key"):
        models.ask("gemini", "q", api_key="k")
    assert no_waiting == []


def test_missing_key_is_caught_before_calling(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(models.ModelError, match="No API key"):
        models.ask("gemini", "q")


def test_retired_model_falls_back(monkeypatch):
    def fake(q, model, key):
        if model == "gemini-3.5-flash":
            raise Exception("404 NOT_FOUND: model not found")
        return f"answered by {model}"

    use_fake_gemini(monkeypatch, fake)
    assert "flash-lite" in models.ask("gemini", "q", api_key="k")


def test_server_error_gives_up_on_one_question_without_trying_every_backup(monkeypatch, no_waiting):
    tried = []

    def fake(q, model, key):
        tried.append(model)
        raise Exception("500 internal error")

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.CallFailed):
        models.ask("gemini", "q", api_key="k")
    assert set(tried) == {"gemini-3.5-flash"}
    assert no_waiting == [1, 2, 4]


def test_timeout_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake(q, model, key):
        calls["n"] += 1
        raise Exception("ReadTimeout: The read operation timed out")

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.CallFailed, match="timed out"):
        models.ask("gemini", "q", api_key="k")
    assert calls["n"] == 1


def test_each_caller_uses_their_own_key(monkeypatch):
    """Two visitors on the web app at once must never end up on each other's keys."""
    seen = []
    use_fake_gemini(monkeypatch, lambda q, model, key: seen.append(key) or "ok")
    models.ask("gemini", "q", api_key="visitor-A")
    models.ask("gemini", "q", api_key="visitor-B")
    assert seen == ["visitor-A", "visitor-B"]


def test_run_stops_early_instead_of_grinding_through_every_question(monkeypatch):
    calls = {"n": 0}

    def always_fails(*a, **k):
        calls["n"] += 1
        raise models.CallFailed("503 service unavailable")

    monkeypatch.setattr(models, "ask", always_fails)
    with pytest.raises(models.ModelError, match="3 failed calls in a row"):
        run_check.run_business("Goodthing Coffee", "coffee shop", "Burlingame, CA",
                               ["gemini"], runs=1, num_questions=20, verbose=False)
    assert calls["n"] == 3


def test_study_asks_once_no_matter_how_many_businesses(monkeypatch):
    """8 competitors should cost the same as 1. The first version would have cost 8x."""
    calls = {"n": 0}

    def fake_ask(provider, question, **k):
        calls["n"] += 1
        return ("1. **Philz Coffee** - great.\n2. **Goodthing Coffee** - cozy.\n"
                "3. **Blue Bottle Coffee** - pour-overs.\n4. Peet's Coffee - classic.")

    monkeypatch.setattr(models, "ask", fake_ask)
    study, rows = run_check.build_study({"name": "Goodthing Coffee", "aliases": []},
                                        "coffee shop", "Burlingame, CA", ["gemini"],
                                        runs=2, num_questions=5)
    assert calls["n"] == 10                              # 5 questions x 2 runs, total
    names = [r["business"] for r in study["results"]]
    assert "Philz Coffee" in names and "Goodthing Coffee" in names
    assert names.count("Goodthing Coffee") == 1          # target not duplicated as a "competitor"
    assert next(r for r in study["results"] if r["business"] == "Goodthing Coffee")["is_target"]


def test_progress_callback_reports_every_call():
    seen = []
    run_check.run_business("Goodthing Coffee", "coffee shop", "Burlingame, CA", ["demo"],
                           runs=1, num_questions=4, verbose=False,
                           on_progress=lambda d, t: seen.append((d, t)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_demo_mode_needs_no_key():
    assert models.ask("demo", "best coffee?", business_name="Goodthing Coffee").startswith("Here are")
