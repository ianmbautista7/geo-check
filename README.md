# GEO Check

**Do AI assistants recommend your business?**

When someone asks ChatGPT "best coffee shop in Burlingame," the model names three or four
places. Everyone else is invisible. There is no Search Console for that. GEO Check measures it.

*GEO stands for generative engine optimization: the emerging practice of getting your business
named inside AI answers, the way SEO gets you ranked inside Google results.*

🔗 **[Live app](ADD_YOUR_STREAMLIT_URL_HERE)** · Built by [Ian Bautista](https://linkedin.com/in/ian-bautista-sjsu)

---

## What it does

1. Takes a business name, category, and city
2. Builds 20 realistic buyer questions for that category, **never containing the business name**
3. Asks each question to 2-3 AI models, 3 times each
4. Measures whether the business was named, how early, and in what tone
5. Returns a 0-100 Visibility Score and three plain-English next steps

The business name is deliberately left out of every question. If we asked "is Goodthing Coffee
good?" the model would talk about Goodthing regardless. The only result worth having is whether
the model brings them up unprompted.

## The finding

> **RESULTS GO HERE ONCE THE REAL RUN IS DONE.**
> Replace this block with the actual leaderboard, the gap between the top and bottom business,
> and the biggest surprise. Do not publish demo numbers as real numbers.

## How the score works

```
Visibility Score = 60 × mention_rate + 25 × position_score + 15 × sentiment_score
```

| Component | Weight | Why that weight |
|---|---|---|
| Mention rate | 60% | Being named is the binary that matters. Position and tone are irrelevant if you are never in the answer. |
| Position | 25% | Named fifth of five is real but weak. Normalized so first = 1.0. |
| Sentiment | 15% | Most AI answers are neutral-to-positive by default, so this varies least and carries the least signal. |

**Consistency is reported separately, not folded into the score.** A 50 that is rock solid and a
50 that swings run to run are different problems needing different fixes. Averaging them into one
number would hide which one you have.

## The part that was actually hard

**The models give a different answer every time you ask.** Ask the same question twice and a
business can appear once and vanish once. A single run is not a measurement, it is a coin flip.

That is why every question runs 3 times, and why the tool reports a consistency rating alongside
the score. An unstable mention means thin evidence about you online, and the fix is different from
the fix for a stable low score.

This is the same problem anyone shipping an AI feature has to solve: how do you evaluate a system
that will not give you the same answer twice?

## Design decisions and what they cost

| Decision | Chose | Gave up | Why |
|---|---|---|---|
| Sentiment | Keyword lexicon | LLM-judged sentiment | Free, instant, auditable. Using an AI to grade an AI adds cost and a second layer of randomness to debug. It is crude on sarcasm, and that is a known limitation. |
| Runs per question | 3 | Tighter statistics | Enough to see whether a mention is stable. Cost and runtime scale linearly with this number. |
| Models | 2-3 | Full coverage | Each model multiplies cost and runtime. Two disagreeing models already proves the variance point. |
| Storage | CSV | A database | No accounts in v1, so nothing needs to persist between users. CSV opens in Excel, which is what a business owner actually wants. |
| Questions | Fixed templates | AI-generated questions | Templates are identical run to run, so a score change reflects the business, not a reshuffled question set. |

## Known limitations

- **Keyword sentiment misreads sarcasm and negation.** "Not bad" scores as negative.
- **No causal claim.** If a business improves after acting on the advice, this tool cannot prove
  the advice caused it. Suggestions are hypotheses to test.
- **Scores are not comparable across time.** Models get updated. Every row records the model
  version and timestamp so old results stay interpretable.
- **Name collisions.** Handled with word-boundary matching and a per-business alias list, but an
  unusual business name can still produce false positives.

## Repo layout

```
app.py                 Streamlit web app (the part people click)
study.json             Which businesses to compare
src/
  questions.py         Question templates, fills in category and city
  models.py            Talks to Claude / OpenAI / Gemini, plus a free demo mode
  scoring.py           Mention detection, position, sentiment, the score itself
  run_check.py         Runs one business end to end, writes the CSV
  run_study.py         Runs several businesses, builds the leaderboard
tests/
  test_scoring.py      12 tests covering the scoring logic
docs/
  PRD.md               Product requirements: problem, metric, tradeoffs, risks
data/                  Output CSVs and saved study results
```

## Run it yourself

```bash
git clone https://github.com/ianmbautista7/geo-check
cd geo-check
pip install -r requirements.txt

# Try it with no API key and no cost:
python src/run_check.py --name "Goodthing Coffee" --category "coffee shop" \
  --city "Burlingame, CA" --providers demo --runs 3

# With a real model (get a free key at aistudio.google.com):
cp .env.example .env     # paste your key into .env
python src/run_check.py --name "Goodthing Coffee" --category "coffee shop" \
  --city "Burlingame, CA" --providers gemini --runs 3

# Compare several businesses:
python src/run_study.py --config study.json --providers gemini --runs 3

# Launch the web app:
streamlit run app.py

# Run the tests:
python -m pytest tests -q
```

**Demo mode** generates realistic fake answers with no API key and no cost, so you can see how the
tool works before spending anything. Demo numbers are clearly labeled and are never presented as
real results.

## Stack

Python · pandas · Streamlit · Gemini / OpenAI / Anthropic APIs · pytest · Streamlit Community Cloud
