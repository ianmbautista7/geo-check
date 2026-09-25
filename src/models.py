"""
models.py
---------
This file's only job: take a question, send it to an AI model, hand back the text answer.

It supports three real providers (Claude, OpenAI, Gemini) plus a "demo" provider
that fakes answers so you can run the whole tool with no API key and no cost.

Everything downstream (scoring, charts) works on plain text, so it does not care
which of these produced the answer. That separation is deliberate: swapping in a
new model later means editing only this file.
"""

import hashlib
import os
import random
import time

# The prompt we wrap around every question. We ask for a numbered list because
# a list gives us a clean, countable position for each business.
SYSTEM_PROMPT = (
    "You are a helpful local recommendation assistant. "
    "Answer with a numbered list of 3 to 5 specific, real businesses by name. "
    "Give one short sentence about each. Do not add extra commentary."
)


class ModelError(Exception):
    """Raised when a provider call fails for a reason worth showing the user."""


# ----------------------------------------------------------------------------
# Real providers
# ----------------------------------------------------------------------------

def _ask_claude(question: str, model: str) -> str:
    import anthropic  # imported here so the app still runs without the package

    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise ModelError("ANTHROPIC_API_KEY is not set.")
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def _ask_openai(question: str, model: str) -> str:
    from openai import OpenAI

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ModelError("OPENAI_API_KEY is not set.")
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    return resp.choices[0].message.content or ""


def _ask_gemini(question: str, model: str) -> str:
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ModelError("GEMINI_API_KEY is not set.")
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=model,
        contents=question,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )
    return resp.text or ""


# ----------------------------------------------------------------------------
# Demo provider (no API key, no cost)
# ----------------------------------------------------------------------------

# Fake competitor names so demo answers look like real answers.
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
    Build a believable fake answer.

    The randomness is SEEDED by question + model + run number. That means the
    same inputs always give the same fake answer (so tests are repeatable), but
    different runs give different answers (so the variability we are trying to
    measure actually shows up).
    """
    seed_text = f"{question}|{model}|{run}"
    seed = int(hashlib.md5(seed_text.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)

    names = _DEMO_COMPETITORS[:]
    rng.shuffle(names)
    picks = names[:4]

    # Insert the target business about 60% of the time, at a random spot.
    # This is what makes the demo score land in a realistic middle range.
    if business_name and rng.random() < 0.6:
        slot = rng.randint(0, len(picks) - 1)
        picks[slot] = business_name

    lines = [f"Here are some good options:\n"]
    for i, name in enumerate(picks, 1):
        lines.append(f"{i}. {name} - {rng.choice(_DEMO_BLURBS)}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# The one function the rest of the app calls
# ----------------------------------------------------------------------------

PROVIDERS = {
    "claude": ("claude-sonnet-4-5", _ask_claude),
    "openai": ("gpt-4o-mini", _ask_openai),
    "gemini": ("gemini-2.0-flash", _ask_gemini),
    "demo": ("demo-v1", None),
}


def ask(provider: str, question: str, business_name: str = "", run: int = 1,
        model: str = None, retries: int = 2) -> str:
    """
    Ask one model one question and return the answer text.

    provider: "claude", "openai", "gemini", or "demo"
    retries:  network calls fail sometimes. We retry with a growing wait
              (1s, then 2s) instead of losing the whole run over one blip.
    """
    if provider not in PROVIDERS:
        raise ModelError(f"Unknown provider: {provider}")

    default_model, fn = PROVIDERS[provider]
    model = model or default_model

    if provider == "demo":
        return _ask_demo(question, model, business_name, run)

    last_error = None
    for attempt in range(retries + 1):
        try:
            return fn(question, model)
        except ModelError:
            raise  # missing key: retrying will not help
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise ModelError(f"{provider} failed after {retries + 1} tries: {last_error}")


def model_id(provider: str, model: str = None) -> str:
    """The exact model version, recorded on every row so old results stay interpretable."""
    return model or PROVIDERS.get(provider, (provider, None))[0]


if __name__ == "__main__":
    print(ask("demo", "What are the best coffee shops in Burlingame, CA?",
              business_name="Goodthing Coffee", run=1))
