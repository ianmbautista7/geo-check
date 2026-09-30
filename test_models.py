"""
test_models.py
--------------
Tests for how models.py handles failures. Run with:  python -m pytest tests -q

We never call a real API here. Instead we swap in a fake "Gemini" function
that fails on purpose, so we can prove the retry and fallback logic works
without a key, without cost, and without waiting.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import models


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Replace time.sleep so retry waits are instant, and record how long we'd have waited."""
    waits = []
    monkeypatch.setattr(models.time, "sleep", lambda s: waits.append(s))
    models.last_model_used.clear()
    return waits


def use_fake_gemini(monkeypatch, fake):
    monkeypatch.setitem(models.PROVIDERS, "gemini", ("gemini-3.5-flash", fake))


def test_retired_model_falls_back_to_the_next_one(monkeypatch):
    """If Google retires the pinned model, we switch to a fallback instead of crashing."""
    def fake(question, model):
        if model == "gemini-3.5-flash":
            raise Exception("404 NOT_FOUND: model not found")
        return f"1. Goodthing Coffee - answered by {model}"

    use_fake_gemini(monkeypatch, fake)
    answer = models.ask("gemini", "best coffee?")
    assert "gemini-flash-latest" in answer
    assert models.model_id("gemini") == "gemini-flash-latest"  # the CSV records the truth


def test_rate_limit_waits_longer_then_succeeds(monkeypatch, no_waiting):
    """Free tier says 'slow down' twice, then lets us through. We wait 10s, then 20s."""
    calls = {"n": 0}

    def fake(question, model):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise Exception("429 RESOURCE_EXHAUSTED: quota exceeded")
        return "1. Corner Cup - fine"

    use_fake_gemini(monkeypatch, fake)
    assert models.ask("gemini", "best coffee?").startswith("1.")
    assert no_waiting == [10, 20]   # waited longer each time, then got through


def test_ordinary_blip_uses_short_waits(monkeypatch, no_waiting):
    calls = {"n": 0}

    def fake(question, model):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("connection reset")
        return "ok"

    use_fake_gemini(monkeypatch, fake)
    assert models.ask("gemini", "q") == "ok"
    assert no_waiting == [1]


def test_missing_key_fails_fast_without_retrying(monkeypatch, no_waiting):
    """No key is not a temporary problem. Retrying would just waste a minute."""
    def fake(question, model):
        raise models.ModelError("GEMINI_API_KEY is not set.")

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.ModelError):
        models.ask("gemini", "q")
    assert no_waiting == []


def test_gives_up_on_one_question_without_trying_every_backup(monkeypatch, no_waiting):
    """A server error isn't fixed by switching models, so we don't triple the wait."""
    tried = []

    def fake(question, model):
        tried.append(model)
        raise Exception("500 internal error")

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.CallFailed):
        models.ask("gemini", "q")
    assert set(tried) == {"gemini-3.5-flash"}   # never touched the backups
    assert no_waiting == [1, 2, 4]              # short waits, then gave up


def test_bad_key_stops_immediately(monkeypatch, no_waiting):
    """This is the bug that made the app look frozen: a rejected key got retried for minutes."""
    def fake(question, model):
        raise Exception("400 INVALID_ARGUMENT: API key not valid. Please pass a valid API key.")

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.ModelError, match="rejected the API key"):
        models.ask("gemini", "q")
    assert no_waiting == []


def test_every_model_missing_is_a_setup_error(monkeypatch):
    def fake(question, model):
        raise Exception("404 NOT_FOUND")

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.ModelError, match="None of the gemini models"):
        models.ask("gemini", "q")


def test_demo_mode_needs_no_key():
    answer = models.ask("demo", "best coffee?", business_name="Goodthing Coffee", run=1)
    assert answer.startswith("Here are some good options")


def test_run_stops_early_instead_of_grinding_through_every_question(monkeypatch):
    """Three failures in a row means something is broken. Stop and say so."""
    import run_check

    calls = {"n": 0}

    def always_fails(*args, **kwargs):
        calls["n"] += 1
        raise models.CallFailed("503 service unavailable")

    monkeypatch.setattr(models, "ask", always_fails)
    with pytest.raises(models.ModelError, match="3 failed calls in a row"):
        run_check.run_business("Goodthing Coffee", "coffee shop", "Burlingame, CA",
                               ["gemini"], runs=1, num_questions=20, verbose=False)
    assert calls["n"] == 3   # stopped at 3, not 20


def test_progress_callback_reports_every_call():
    import run_check

    seen = []
    run_check.run_business("Goodthing Coffee", "coffee shop", "Burlingame, CA", ["demo"],
                           runs=1, num_questions=4, verbose=False,
                           on_progress=lambda d, t: seen.append((d, t)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_timeout_is_not_retried(monkeypatch, no_waiting):
    """A call that already hung for 60 seconds gets skipped, not retried three more times."""
    calls = {"n": 0}

    def fake(question, model):
        calls["n"] += 1
        raise Exception("ReadTimeout: The read operation timed out")

    use_fake_gemini(monkeypatch, fake)
    with pytest.raises(models.CallFailed, match="timed out"):
        models.ask("gemini", "q")
    assert calls["n"] == 1
