"""
scoring.py
----------
Takes raw AI answer text and turns it into numbers.

Four questions we ask of every answer:
  1. Was the business mentioned at all?          -> find_mention()
  2. How early in the list was it?               -> position gets normalized 0-1
  3. What tone was used about it?                -> score_sentiment()
  4. Across all answers, how visible are they?   -> visibility_score()

No AI is used in this file. Everything here is plain string work, which means
it is fast, free, and you can point at the exact line that produced any number.
"""

import re
import statistics

# ----------------------------------------------------------------------------
# 1. Did the business get mentioned, and where?
# ----------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Lowercase and strip punctuation so 'Goodthing Coffee!' matches 'goodthing coffee'."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_items(answer: str):
    """
    Break an answer into its list items.

    We look for lines that start like "1." or "2)" or "- ". Those are the
    recommendations. If the model wrote a paragraph instead, we fall back to
    splitting on sentences so we still get an ordering.
    """
    lines = [ln.strip() for ln in answer.splitlines() if ln.strip()]
    items = [ln for ln in lines if re.match(r"^\s*(\d+[\.\)]|[-*•])\s+", ln)]
    if items:
        return items
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()]


def find_mention(answer: str, business_name: str, aliases=None):
    """
    Look for the business in the answer.

    Returns a dict:
        mentioned  True/False
        position   which list item it was in, 1 = first (None if not mentioned)
        total      how many items were in the list
        snippet    the sentence it appeared in, used for sentiment

    Matching uses word boundaries (\\b). Without that, "Bean" would match
    "Beanstalk" and inflate the score. The alias list exists because models
    write "Good Thing Coffee" or just "Goodthing" and all of those should count.
    """
    names = [business_name] + list(aliases or [])
    patterns = [re.compile(r"\b" + re.escape(normalize(n)) + r"\b") for n in names if n.strip()]

    items = split_items(answer)
    for i, item in enumerate(items, start=1):
        item_norm = normalize(item)
        if any(p.search(item_norm) for p in patterns):
            return {"mentioned": True, "position": i, "total": len(items), "snippet": item}

    return {"mentioned": False, "position": None, "total": len(items), "snippet": ""}


def position_score(position, total):
    """
    Turn 'ranked 2nd of 5' into a 0-1 number.

    First place = 1.0, last place = close to 0. The formula is
    (total - position + 1) / total, which spaces the ranks evenly.
    Not mentioned = 0.0.
    """
    if not position or not total:
        return 0.0
    return (total - position + 1) / total


# ----------------------------------------------------------------------------
# 2. What tone was used?
# ----------------------------------------------------------------------------

POSITIVE_WORDS = {
    "best", "great", "excellent", "favorite", "love", "loved", "amazing",
    "outstanding", "top", "recommend", "recommended", "popular", "must",
    "fantastic", "perfect", "rave", "beloved", "standout", "gem", "cozy",
    "friendly", "consistently", "quality", "worth",
}

NEGATIVE_WORDS = {
    "overrated", "crowded", "expensive", "pricey", "slow", "rude", "mediocre",
    "disappointing", "avoid", "miss", "inconsistent", "cramped", "loud",
    "underwhelming", "limited", "though", "but",
}


def score_sentiment(snippet: str):
    """
    Count positive and negative words in the sentence the business was named in.

    More positive than negative -> "positive" (1.0)
    More negative than positive -> "negative" (0.0)
    Tie or neither              -> "neutral"  (0.5)

    This is a lexicon, not an AI. It is crude on sarcasm and on phrases like
    "not bad." We accepted that in v1 because it is free, instant, and every
    result is traceable to a specific word. See the PRD tradeoff table.
    """
    if not snippet:
        return "none", 0.0
    words = set(normalize(snippet).split())
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    if pos > neg:
        return "positive", 1.0
    if neg > pos:
        return "negative", 0.0
    return "neutral", 0.5


# ----------------------------------------------------------------------------
# 3. Roll everything up
# ----------------------------------------------------------------------------

WEIGHT_MENTION = 60
WEIGHT_POSITION = 25
WEIGHT_SENTIMENT = 15


def _total(row):
    """
    Small compatibility helper.

    find_mention() calls the list length "total". The CSV column is named
    "total_items" because "total" is too vague in a spreadsheet. This lets
    both spellings work so the two files don't have to agree on wording.
    """
    return row.get("total") if row.get("total") is not None else row.get("total_items")


def visibility_score(rows):
    """
    Turn a list of per-answer results into one 0-100 score plus supporting stats.

    rows: list of dicts, each with keys mentioned, position, total, sentiment_value

    Important detail: mention rate is averaged over ALL runs, but position and
    sentiment are averaged over MENTIONED runs only. Averaging position over
    every run would double-punish a miss, since a miss already costs the full
    60-point mention component.
    """
    if not rows:
        return {"score": 0.0, "mention_rate": 0.0, "avg_position": None,
                "avg_position_score": 0.0, "avg_sentiment": 0.0,
                "runs": 0, "mentions": 0}

    total_runs = len(rows)
    hits = [r for r in rows if r["mentioned"]]

    mention_rate = len(hits) / total_runs
    avg_pos_score = (
        sum(position_score(r["position"], _total(r)) for r in hits) / len(hits)
        if hits else 0.0
    )
    avg_sentiment = (
        sum(r["sentiment_value"] for r in hits) / len(hits) if hits else 0.0
    )
    avg_position = (
        sum(r["position"] for r in hits) / len(hits) if hits else None
    )

    score = (
        WEIGHT_MENTION * mention_rate
        + WEIGHT_POSITION * avg_pos_score
        + WEIGHT_SENTIMENT * avg_sentiment
    )

    return {
        "score": round(score, 1),
        "mention_rate": round(mention_rate, 3),
        "avg_position": round(avg_position, 2) if avg_position else None,
        "avg_position_score": round(avg_pos_score, 3),
        "avg_sentiment": round(avg_sentiment, 3),
        "runs": total_runs,
        "mentions": len(hits),
    }


def consistency(rows):
    """
    How stable is the mention across repeat runs of the SAME question?

    We group rows by question, get each question's mention rate, then take the
    standard deviation of those rates. Low spread means a reliable mention.
    Reported separately from the score on purpose: a 50 that is rock solid and a
    50 that swings wildly are different problems and need different advice.
    """
    by_question = {}
    for r in rows:
        by_question.setdefault(r["question"], []).append(1 if r["mentioned"] else 0)

    rates = [sum(v) / len(v) for v in by_question.values()]
    if len(rates) < 2:
        return {"spread": 0.0, "label": "not enough data"}

    spread = statistics.pstdev(rates)
    if spread < 0.15:
        label = "high"
    elif spread < 0.30:
        label = "medium"
    else:
        label = "low"
    return {"spread": round(spread, 3), "label": label}


# ----------------------------------------------------------------------------
# 4. Turn numbers into advice
# ----------------------------------------------------------------------------

def suggestions(summary, cons):
    """Plain-English next steps, picked from the numbers. Max 3, ordered by impact."""
    out = []
    rate = summary["mention_rate"]

    if rate == 0:
        out.append(
            "AI models never named you. Start with the basics they read from: claim and fill out "
            "your Google Business Profile, and get listed on Yelp and TripAdvisor with full hours, "
            "photos, and a description that uses your category and city in plain words."
        )
    elif rate < 0.4:
        out.append(
            "You show up in under half of answers. Get mentioned in content models trust: local "
            "'best of' roundups, neighborhood blogs, and Reddit threads about your city. Those "
            "list-style pages are what models pull from most."
        )
    else:
        out.append(
            "You already show up in most answers. Protect that by keeping your listings current "
            "and adding fresh third-party mentions a few times a year."
        )

    if summary["avg_position"] and summary["avg_position"] > 2.5:
        out.append(
            f"When you are named you land around #{summary['avg_position']:.0f} in the list. "
            "Models tend to rank by how much corroborating detail they have. Add specifics to "
            "your listings and site: what you are known for, price range, and standout items."
        )

    if summary["avg_sentiment"] < 0.5 and summary["mentions"] > 0:
        out.append(
            "The tone around you skews neutral or negative. Look at what recent reviews complain "
            "about, fix what you can, and respond publicly. Models echo review language."
        )
    elif cons["label"] == "low":
        out.append(
            "Your mentions are unstable, appearing in some runs and not others. That usually means "
            "thin evidence about you online. More independent sources saying the same things about "
            "you makes the mention stick."
        )

    return out[:3]
