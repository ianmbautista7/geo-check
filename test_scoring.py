"""
test_scoring.py
---------------
Tests for the scoring logic. Run with:  python -m pytest tests -q

Why these exist: scoring.py is where every number on the resume comes from.
If find_mention() has a bug, every claim you make is wrong. These tests pin
down the behavior so a later change can't silently break it.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import scoring


ANSWER = """Here are some good options:
1. Blue Ridge Coffee - A local favorite known for friendly service.
2. Goodthing Coffee - Excellent coffee and a great place to sit and work.
3. Corner Cup - A bit hit or miss, but worth a try.
"""


def test_finds_the_business_and_its_position():
    r = scoring.find_mention(ANSWER, "Goodthing Coffee")
    assert r["mentioned"] is True
    assert r["position"] == 2
    assert r["total"] == 3


def test_misses_a_business_that_is_not_there():
    r = scoring.find_mention(ANSWER, "Starbucks")
    assert r["mentioned"] is False
    assert r["position"] is None


def test_word_boundaries_stop_false_matches():
    """'Bean' must not match 'Beanstalk'. This is the bug that would inflate every score."""
    text = "1. Beanstalk Roasters - Great espresso."
    assert scoring.find_mention(text, "Bean")["mentioned"] is False
    assert scoring.find_mention(text, "Beanstalk Roasters")["mentioned"] is True


def test_aliases_catch_alternate_spellings():
    text = "1. Good Thing Coffee - A neighborhood staple."
    r = scoring.find_mention(text, "Goodthing Coffee", aliases=["Good Thing Coffee"])
    assert r["mentioned"] is True


def test_punctuation_does_not_break_matching():
    text = "1. **Goodthing Coffee!** - Worth the trip."
    assert scoring.find_mention(text, "Goodthing Coffee")["mentioned"] is True


def test_position_score_rewards_being_first():
    assert scoring.position_score(1, 5) == 1.0
    assert scoring.position_score(5, 5) == 0.2
    assert scoring.position_score(None, 5) == 0.0


def test_sentiment_reads_tone():
    assert scoring.score_sentiment("Excellent coffee, a real gem.")[0] == "positive"
    assert scoring.score_sentiment("Overrated and expensive.")[0] == "negative"
    assert scoring.score_sentiment("It is a coffee shop on Main Street.")[0] == "neutral"


def test_perfect_visibility_scores_100():
    rows = [{"mentioned": True, "position": 1, "total": 3, "sentiment_value": 1.0}] * 5
    assert scoring.visibility_score(rows)["score"] == 100.0


def test_never_mentioned_scores_zero():
    rows = [{"mentioned": False, "position": None, "total": 3, "sentiment_value": 0.0}] * 5
    assert scoring.visibility_score(rows)["score"] == 0.0


def test_position_is_averaged_over_hits_not_all_runs():
    """
    Half the runs miss. Mention rate should be 0.5, but the average position
    should reflect only the run where it was actually found, not be dragged
    down by the miss. A miss is already punished by the 60-point mention weight.
    """
    rows = [
        {"mentioned": True, "position": 1, "total": 4, "sentiment_value": 1.0},
        {"mentioned": False, "position": None, "total": 4, "sentiment_value": 0.0},
    ]
    s = scoring.visibility_score(rows)
    assert s["mention_rate"] == 0.5
    assert s["avg_position"] == 1.0
    assert s["avg_position_score"] == 1.0


def test_consistency_flags_unstable_mentions():
    steady = [{"question": f"q{i}", "mentioned": True} for i in range(6)]
    assert scoring.consistency(steady)["label"] == "high"

    swingy = [{"question": "q1", "mentioned": True}, {"question": "q1", "mentioned": True},
              {"question": "q2", "mentioned": False}, {"question": "q2", "mentioned": False}]
    assert scoring.consistency(swingy)["label"] == "low"


def test_paragraph_answers_still_get_parsed():
    """Models don't always give a numbered list. We fall back to sentences."""
    text = "I'd try Blue Ridge Coffee first. Goodthing Coffee is also excellent."
    r = scoring.find_mention(text, "Goodthing Coffee")
    assert r["mentioned"] is True
    assert r["position"] == 2
