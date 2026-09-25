# PRD: AI Search Visibility Checker

**Author:** Ian Bautista
**Status:** v1, MVP in build
**Last updated:** September 2026

---

## 1. Problem

People are shifting from "search and click ten blue links" to "ask an AI and take its answer."
When someone asks ChatGPT or Claude "best coffee shop in Burlingame," the model names three or
four businesses. Everyone else is invisible.

Businesses have no way to see themselves in that answer. Google Search Console shows where you
rank on Google. Nothing shows where you stand inside an AI's recommendation. Small business
owners and early-stage marketers are flying blind on a channel that is already sending them
customers.

The emerging name for optimizing this is GEO, generative engine optimization.

## 2. Users

**Primary: the small business owner or solo marketer.** Runs a coffee shop, a dental practice,
a nonprofit program. Has heard people say "I asked ChatGPT and it recommended you," or worse,
has heard nothing. Non-technical. Wants a number and a to-do list, not a data dump.

**Secondary: the agency or in-house marketer.** Manages several brands, wants to compare them
and show a client a before/after.

## 3. Goals and non-goals

**Goals**
- Tell a business whether AI models recommend them, how prominently, and in what tone
- Make the result repeatable and honest about model randomness
- Give three plain-English actions to improve

**Non-goals for v1**
- No automatic content publishing or fixes. We measure and advise, we do not edit anyone's site.
- No scheduled monitoring or alerting. One-off checks only.
- No accounts, no database. Results save to CSV.
- No claim of causation. We report correlation between content presence and AI mentions.

## 4. How it works

1. User enters business name, category, and city.
2. The tool fills ~20 question templates for that category, producing realistic buyer questions.
3. Each question runs against 2-3 AI models, 3 times each. Three runs is the point, not overhead:
   models are non-deterministic and a single run is not evidence.
4. Every answer is parsed for: is the business named, where in the list, and in what tone.
5. Results roll up into one 0-100 Visibility Score plus a consistency rating.

## 5. The metric

```
Visibility Score = 60 x mention_rate
                 + 25 x position_score
                 + 15 x sentiment_score
```

**Mention rate (60%).** Share of all runs where the business appears at all.
Weighted heaviest because being named is the binary that matters. Position and tone are
irrelevant if you are never in the answer.

**Position score (25%).** Where in the answer the business shows up, normalized so first
place scores 1.0 and last place scores near 0. Being named fifth out of five is real but weak.

**Sentiment score (15%).** Tone of the sentence you are named in, mapped positive 1.0 /
neutral 0.5 / negative 0.0. Lowest weight because most AI answers are neutral-to-positive by
default, so this varies least and carries the least signal.

**Consistency (reported, not scored).** How much the mention rate swings across the 3 runs.
Low consistency means a fragile mention that could vanish tomorrow. This is surfaced as a
separate label rather than folded into the score, because mixing "how visible" and "how stable"
into one number hides which one is the problem.

## 6. Success criteria

- Runs a full check on a real business in under 5 minutes and under $1 of API spend
- Two back-to-back checks of the same business land within 10 points of each other
- A real small business owner reads the output and can name their next action without help

## 7. Key tradeoffs

| Decision | Chose | Gave up | Why |
|---|---|---|---|
| Sentiment method | Keyword lexicon | LLM-judged sentiment | Free, instant, and auditable. Using an AI to grade an AI adds cost and a second layer of randomness to debug. Upgrade path exists. |
| Runs per question | 3 | 5-10 (tighter stats) | 3 is enough to see whether a mention is stable. Cost and runtime scale linearly. |
| Models | 2-3 | All major models | Each added model multiplies cost and runtime. Two disagreeing models already proves the variance point. |
| Storage | CSV | A database | No accounts in v1, so there is nothing to persist between users. CSV opens in Excel, which is what the user actually wants. |
| Question source | Fixed templates | AI-generated questions | Templates are identical run to run, so score changes reflect the business, not a reshuffled question set. |

## 8. Risks

- **Model randomness.** Mitigated by repeat runs and a reported consistency rating.
- **Name collisions.** "Goodthing" may match unrelated text. Mitigated by word-boundary matching
  and an alias list per business.
- **Models change under us.** A score from March and a score from June may not be comparable.
  Every result row records the model version and timestamp.
- **Advice may not work.** GEO is new and the causal link is unproven. Suggestions are framed as
  hypotheses to test, not guarantees.

## 9. Roadmap after v1

- LLM-judged sentiment as an opt-in upgrade, benchmarked against the keyword baseline
- Competitor view: who does get recommended for your questions, and what they have that you do not
- Scheduled re-checks and a trend line
- Source tracing: which pages the model appears to be drawing on
