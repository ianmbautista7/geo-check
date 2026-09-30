"""
models.py
---------
This file's only job: take a question, send it to an AI model, hand back the text answer.

It supports three real providers (Claude, OpenAI, Gemini) plus a "demo" provider
that fakes answers so you can run the whole tool with no API key and no cost.

Everything downstream (scoring, charts) works on plain text, so it does not care
which of these produced the answer. Swapping in a new model means editing only this file.

The hard part of this file is not asking the question. It's handling the ways a free
API tier says "no": too fast, too many today, bad key, model retired, server hung.
Each one needs a different response, and getting that wrong is what made the first
live version of the app look frozen.
"""

import hashlib
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

# The prompt we wrap around every question. We ask for a numbered list because
# a list gives us a clean, countable position for each business.
SYSTEM_PROMPT = (
    "You are a helpful local recommendation assistant. "
    "Answer with a numbered list of 3 to 5 specific, real businesses by name. "
    "Give one short sentence about each. Do not add extra commentary."
)


class ModelError(Exception):
    """A problem that will hit every call the same way (bad key, daily limit used up). Stop the run."""


class CallFailed(Exception):
    """One question failed even after retries. Could be a blip, so the run can keep going."""


# ----------------------------------------------------------------------------
# Real providers. Each takes the key directly instead of reading a shared
# setting, so two people using the web app at once can't end up on each
# other's keys.
# ----------------------------------------------------------------------------

def _ask_claude(question: str, model: str, api_key: str) -> str:
    import anthropic  # imported here so the app still runs without the package

    client = anthropic.Anthropic(api_key=api_key, timeout=60)
    resp = client.messages.create(
        model=model,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def _ask_openai(question: str, model: str, api_key: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=60)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    return resp.choices[0].message.content or ""


def _ask_gemini(question: str, model: str, api_key: str) -> str:
    from google import genai
    from google.genai import types

    # timeout is in milliseconds. Without it, a call that never gets an answer
    # would wait forever and the app would look frozen.
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60_000))
    resp = client.models.generate_content(
        model=model,
        contents=question,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )
    return resp.text or ""


# ----------------------------------------------------------------------------
# Demo provider (no API key, no cost)
# ----------------------------------------------------------------------------

_DEMO_COMPETITORS = [
    "Blue Ridge Coffee", "Morning Fog Cafe", "Peninsula Roasters",
    "The Daily Grind", "Sunbeam Coffee Bar", "Third Wave Coffee Co",
    "Corner Cup", "Alder & Oak Cafe",
]

_DEMO_BLURBS = [
    "A local favorite known for friendly service.",
    "People rave about the atmosphere here.",
    "Solid option, though it gets crowded at peak hours.",
    "Consistently good quality and reasonable prices.",
    "A bit hit or miss, but worth a try.",
    "Excellent coffee and a great place to sit and work.",
]


def _ask_demo(question: str, model: str, business_name: str = "", run: int = 1) -> str:
    """
    Build a believable fake answer. The randomness is seeded by question + model +
    run, so the same inputs always give the same fake answer (repeatable tests), but
    different runs differ (so the run-to-run variability we measure shows up).
    """
    seed = int(hashlib.md5(f"{question}|{model}|{run}".encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)

    names = _DEMO_COMPETITORS[:]
    rng.shuffle(names)
    picks = names[:4]

    if business_name and rng.random() < 0.6:
        picks[rng.randint(0, len(picks) - 1)] = business_name

    lines = ["Here are some good options:\n"]
    for i, name in enumerate(picks, 1):
        lines.append(f"{i}. {name} - {rng.choice(_DEMO_BLURBS)}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Which model to use
# ----------------------------------------------------------------------------

PROVIDERS = {
    "claude": ("claude-sonnet-4-5", _ask_claude, "ANTHROPIC_API_KEY"),
    "openai": ("gpt-4o-mini", _ask_openai, "OPENAI_API_KEY"),
    "gemini": ("gemini-3.5-flash", _ask_gemini, "GEMINI_API_KEY"),
    "demo": ("demo-v1", None, None),
}

# Google's free tier gives each model its OWN daily allowance (about 20 requests).
# So when one model's allowance runs out, the next model on this list still has
# its own. Models that don't exist anymore just get skipped.
FALLBACK_MODELS = {
    "gemini": [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-2.5-flash",
    ],
}

# Remembers which model answered last, so the next call starts there instead of
# re-hitting models we already know are out for the day.
last_model_used = {}

# Models whose daily allowance is used up, and the Pacific date that happened.
# Cleared automatically the next day, because that's when Google resets it.
_exhausted_today = {}


def _pacific_today() -> str:
    # Pacific is UTC-8 or UTC-7. Using -8 means we might wait an extra hour in
    # summer before retrying a model, which is the safe direction to be wrong.
    return (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d")


def _mark_exhausted(model: str):
    _exhausted_today[model] = _pacific_today()


def _is_exhausted(model: str) -> bool:
    return _exhausted_today.get(model) == _pacific_today()


# ----------------------------------------------------------------------------
# Reading error messages. Each kind of "no" gets a different response.
# ----------------------------------------------------------------------------

def _text(err) -> str:
    return str(err).lower()


def _is_daily_limit(err) -> bool:
    """Used up today's allowance. Waiting a few seconds won't help. Only tomorrow will."""
    t = _text(err).replace(" ", "")
    return "perday" in t or "requestsperday" in t


def _is_rate_limit(err) -> bool:
    """Too many requests too fast. This one DOES go away if you wait."""
    t = _text(err)
    return "429" in t or "resource_exhausted" in t or "rate limit" in t or "quota" in t


def _retry_after(err):
    """
    Google tells you how long to wait ("Please retry in 22.2s"). Using its number
    is better than guessing: guess too short and you get refused again, guess too
    long and the user sits there for nothing.
    """
    t = str(err)
    m = re.search(r"retry in ([\d.]+)\s*s", t, re.I) or re.search(r"retryDelay'?\"?:\s*'?\"?(\d+)s", t)
    return float(m.group(1)) if m else None


def _is_auth_error(err) -> bool:
    """
    A bad or blocked key. Retrying won't fix it, so stop immediately and say so.
    Status codes are matched as whole words: a wait time like "22.4031s" contains
    the digits 403 and must not be mistaken for "access denied".
    """
    t = _text(err)
    if re.search(r"\b(401|403)\b", t):
        return True
    return any(k in t for k in (
        "api key not valid", "api_key_invalid", "invalid api key",
        "permission_denied", "unauthenticated", "permission denied",
    ))


def _is_timeout(err) -> bool:
    t = _text(err)
    return "timed out" in t or "timeout" in t or "deadline" in t


def _is_model_missing(err) -> bool:
    """A 404 on the model name means it was renamed or retired."""
    t = _text(err)
    return "404" in t or "not found" in t or "not_found" in t


# ----------------------------------------------------------------------------
# The one function the rest of the app calls
# ----------------------------------------------------------------------------

def ask(provider: str, question: str, business_name: str = "", run: int = 1,
        model: str = None, api_key: str = None, retries: int = 3) -> str:
    """
    Ask one model one question and return the answer text.

    api_key: pass it in directly. If you don't, we look for the usual environment
             variable (e.g. GEMINI_API_KEY), which is how the command line works.

    How each kind of failure is handled:
      - Daily limit used up  -> mark that model done for today, move to the next model
      - Too fast (per-minute) -> wait as long as Google says, then retry the same model
      - Model retired (404)   -> move to the next model
      - Bad key               -> stop everything immediately, it won't fix itself
      - Timed out (60s)       -> skip this question, don't wait another 60s
      - Anything else         -> short wait (1s, 2s, 4s) and retry, in case it was a blip
    """
    if provider not in PROVIDERS:
        raise ModelError(f"Unknown provider: {provider}")

    default_model, fn, env_var = PROVIDERS[provider]

    if provider == "demo":
        last_model_used[provider] = model or default_model
        return _ask_demo(question, model or default_model, business_name, run)

    key = api_key or os.getenv(env_var or "")
    if not key:
        raise ModelError(f"No API key for {provider}. Set {env_var} or enter one.")

    if model:
        candidates = [model]
    else:
        candidates = [last_model_used.get(provider, default_model), default_model,
                      *FALLBACK_MODELS.get(provider, [])]
        candidates = list(dict.fromkeys(c for c in candidates if c))
    candidates = [c for c in candidates if not _is_exhausted(c)]

    if not candidates:
        raise ModelError(
            f"Every {provider} model has used up today's free allowance. "
            "It resets at midnight Pacific time.")

    last_error = None
    for current in candidates:
        for attempt in range(retries + 1):
            try:
                answer = fn(question, current, key)
                last_model_used[provider] = current
                return answer
            except ModelError:
                raise
            except ImportError as e:
                raise ModelError(f"The {provider} library isn't installed: {e}")
            except Exception as e:
                last_error = e
                # Order matters: the specific checks go first, so a quota message
                # that happens to contain other keywords is still read as a quota.
                if _is_daily_limit(e):
                    _mark_exhausted(current)
                    break  # this model is done for today: try the next one
                if _is_model_missing(e):
                    break  # this model is gone: try the next one
                if _is_timeout(e):
                    raise CallFailed(f"{provider} ({current}) timed out: {e}")
                if _is_auth_error(e):
                    raise ModelError(f"{provider} rejected the API key: {e}")
                if attempt < retries:
                    if _is_rate_limit(e):
                        wait = min(65, (_retry_after(e) or 10 * 2 ** attempt) + 1)
                    else:
                        wait = 2 ** attempt
                    time.sleep(wait)
        else:
            # Retries ran out on a model that exists and still has allowance.
            # Switching models won't fix an outage, so give up on this one question.
            raise CallFailed(f"{provider} ({current}) failed: {last_error}")

    if all(_is_exhausted(c) for c in candidates):
        raise ModelError(
            f"Every {provider} model has used up today's free allowance. "
            "It resets at midnight Pacific time.")
    raise ModelError(f"None of the {provider} models worked. Last error: {last_error}")


def model_id(provider: str, model: str = None) -> str:
    """The exact model version that answered, recorded on every row so old results stay interpretable."""
    if model:
        return model
    return last_model_used.get(provider) or PROVIDERS.get(provider, (provider,))[0]


if __name__ == "__main__":
    print(ask("demo", "What are the best coffee shops in Burlingame, CA?",
              business_name="Goodthing Coffee", run=1))
