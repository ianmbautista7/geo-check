# GEO Check

**Do AI assistants recommend your business?**

When someone asks ChatGPT "best coffee shop in Burlingame," the model names three or four
places. Everyone else is invisible. There is no Search Console for that. GEO Check measures it.

*GEO stands for generative engine optimization: the emerging practice of getting your business
named inside AI answers, the way SEO gets you ranked inside Google results.*

🔗 **[Live app](https://geo-check-ian.streamlit.app/)** · Built by [Ian Bautista](https://linkedin.com/in/ian-bautista-sjsu)

---

## What it does

1. Takes a business name, category, and city
2. Asks an AI model realistic customer questions for that category, **never containing the business name**
3. Pulls every business the AI recommends out of the answers, so the competitors are
   discovered from the data instead of hand-picked
4. Scores the target business and each competitor on mention rate, list position, and tone
5. Returns a 0-100 Visibility Score, a leaderboard, and three plain-English next steps

The business name is deliberately left out of every question. If we asked "is Goodthing Coffee
good?" the model would talk about Goodthing regardless. The only result worth having is whether
the model brings them up unprompted.

## The finding

**First study: coffee shops in Burlingame, CA** (Sep 30, 2026, gemini-3.5-flash-lite, 10 questions x 2 runs = 20 answers)

| Rank | Business | Score | Named in |
|---|---|---|---|
| 1 | Peet's Coffee | 69.9 | 70% of answers |
| 2 | Philz Coffee | 60.5 | 50% |
| 3 | Toasty Coffee Bar | 42.2 | 10% |
| 4 | St. Frank Coffee | 39.0 | 25% |
| 5 | Steelhead Coffee | 37.7 | 10% |
| 6 | To Beans | 36.8 | 15% |
| 7 | Canyon Market & Cafe | 35.1 | 15% |
| 8 | Cafe Central | 32.5 | 25% |
| 9 | **Goodthing Coffee** | **0.0** | **0 of 20** |

Goodthing Coffee has 323 Yelp reviews and was covered by the San Francisco Chronicle when it
opened. The AI didn't name it once. Strong review-site presence and AI visibility are not the
same thing, and that gap is exactly what this tool is built to show.

**What this result can and can't say:**
- **One model.** All 20 answers came from gemini-3.5-flash-lite, a smaller model, because the
  main model's free daily limit had been used. A larger model may know more. That's the next test.
- **20 answers from one day.** Enough for a first measurement, not a final verdict.
- **The competitor list is the AI's, unverified.** Models sometimes name places outside the city
  or that don't exist. Checking the list by hand is part of reading the result.

Every answer behind these numbers is in `study_answers.csv`.

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

## The parts that were actually hard

**The models give a different answer every time you ask.** Ask the same question twice and a
business can appear once and vanish once. A single run is not a measurement, it is a coin flip.
That's why every question runs more than once, and why the tool reports a consistency rating
alongside the score.

**The free API tier allows about 20 requests per model per day.** The first design asked each
question separately for every business: 8 businesses x 20 questions x 3 runs = 480 calls. That
could never run for free. The fix came from the design itself: since the business name is never
in the question, one answer can be scored for every business at once. The same comparison now
costs 20 calls. When one model's daily allowance runs out, the tool moves to another model that
still has its own, and records which model produced every answer.

**The first live version looked frozen.** When a call failed, the code retried quietly, then
tried backup models and retried those too, with no time limit and nothing on screen. It turned
out the free daily limit had been hit, and the retries themselves had burned through it. Now
each kind of failure gets its own response: a daily limit switches models immediately, a
per-minute limit waits exactly as long as Google says, a bad key stops in about a second,
a hung call times out at 60 seconds, and three failures in a row stop the run with the real
error message. Each of those cases has a test built from the actual error text.

**The first result gave bad advice.** For a business named in 0 answers, the tool told it to
"get listed on Yelp." Goodthing already had 323 Yelp reviews. The suggestions are rule-based and
can't see what a business already has, so the advice was rewritten to work either way. The
published study was then re-scored from its saved answers, which costs zero API calls and left
every score unchanged.

## Design decisions and what they cost

| Decision | Chose | Gave up | Why |
|---|---|---|---|
| Sentiment | Keyword lexicon | LLM-judged sentiment | Free, instant, auditable. Using an AI to grade an AI adds cost and a second layer of randomness to debug. It is crude on sarcasm, and that is a known limitation. |
| Runs per question | 2 | Tighter statistics | Enough to see whether a mention is stable while fitting the free daily limit. Cost scales linearly with this number. |
| Competitors | Discovered from answers | A hand-picked list | Whoever the AI names most IS the competition. Picking them ourselves would bake our guesses into the result. |
| API key on the live site | Visitors bring their own | Letting anyone use the owner's key | The free tier is tiny. One curious visitor could use up a day's allowance. |
| Models | 2-3 | Full coverage | Each model multiplies cost and runtime. Two disagreeing models already proves the variance point. |
| Storage | CSV | A database | No accounts in v1, so nothing needs to persist between users. CSV opens in Excel, which is what a business owner actually wants. |
| Questions | Fixed templates | AI-generated questions | Templates are identical run to run, so a score change reflects the business, not a reshuffled question set. |

## Known limitations

- **Keyword sentiment misreads sarcasm and negation.** "Not bad" scores as negative.
- **No causal claim.** If a business improves after acting on the advice, this tool cannot prove
  the advice caused it. Suggestions are hypotheses to test.
- **Scores are not comparable across time.** Models get updated and retired. The tool pins a
  specific model version, falls back to a newer one only if the pinned model is shut down, and
  records on every row which model actually answered.
- **Free-tier rate limits.** Free API tiers cap requests per minute. The tool backs off and retries
  (10s, 20s, 40s, 60s) instead of failing, so a full run is slower on the free tier but completes.
- **Name collisions.** Handled with word-boundary matching and a per-business alias list, but an
  unusual business name can still produce false positives.

## Repo layout

```
app.py              Streamlit web app (the part people click)
questions.py        Question templates, fills in category and city
models.py           Talks to Gemini / OpenAI / Claude, handles limits and failures, plus a free demo mode
scoring.py          Mention detection, position, sentiment, the score, competitor discovery
run_check.py        Collects answers once and scores any number of businesses from them
run_study.py        Command-line version of the study
study.json          Which business the command-line study checks
study_results.json  The published study the app shows (appears after the first real run)
study_answers.csv   Every AI answer behind the study, for anyone who wants to check
test_scoring.py     Tests for the scoring and competitor discovery
test_models.py      Tests for every failure case, using real error text from the API
docs/PRD.md         Product requirements: problem, metric, tradeoffs, risks
```

## Run it yourself

```bash
git clone https://github.com/ianmbautista7/geo-check
cd geo-check
pip install -r requirements.txt

# Try it with no API key and no cost:
python run_check.py --name "Goodthing Coffee" --category "coffee shop" --city "Burlingame, CA" --providers demo

# With a real model (free key at aistudio.google.com):
export GEMINI_API_KEY=your-key
python run_study.py --providers gemini --runs 2 --questions 10

# Launch the web app:
streamlit run app.py

# Run the tests:
python -m pytest -q
```

**Demo mode** generates fake answers with no API key and no cost, so you can see how the tool
works before spending anything. Demo results are labeled as fake and never published as real.

## Stack

Python · pandas · Streamlit · Gemini / OpenAI / Anthropic APIs · pytest · Streamlit Community Cloud
