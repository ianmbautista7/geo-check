"""
questions.py
------------
Holds the question templates we ask AI models, and turns them into real questions.

A template is just a sentence with blanks in it, like:
    "best {category} in {city}"

We fill the blanks with the business's category and city. We never put the
business NAME into the question. That is the whole point: we want to see if the
model brings them up on its own.
"""

# Questions that work for any kind of business. {category} and {city} get filled in.
GENERIC_TEMPLATES = [
    "What are the best {plural} in {city}?",
    "Can you recommend a good {category} in {city}?",
    "I'm visiting {city} for the first time. Which {category} should I check out?",
    "What's the most popular {category} in {city}?",
    "Where do locals go for {plural} in {city}?",
    "I'm on a budget. What's a good affordable {category} in {city}?",
    "What's a hidden gem {category} in {city}?",
    "Which {category} in {city} has the best reviews?",
    "Give me a top 5 list of {plural} in {city}.",
    "I have one hour in {city}. Which {category} is worth it?",
]

# Extra questions that only make sense for certain categories.
# The key is a keyword we look for in the user's category text.
CATEGORY_TEMPLATES = {
    "coffee": [
        "Where can I get the best espresso in {city}?",
        "What's a good coffee shop to work from in {city}?",
        "Which {category} in {city} roasts their own beans?",
        "Best place for a latte in {city}?",
        "I want a quiet cafe in {city} to study. Where should I go?",
        "Which coffee shop in {city} has the best pastries?",
        "Where's the best cold brew in {city}?",
        "Independent coffee shops in {city}, not chains. Any recommendations?",
        "Best coffee near downtown {city}?",
        "Which {category} in {city} is good for a first date?",
    ],
    "restaurant": [
        "Where should I go for dinner in {city}?",
        "Best brunch spot in {city}?",
        "Which restaurant in {city} is good for a group of 6?",
        "Where's the best takeout in {city}?",
        "Any restaurants in {city} with good vegetarian options?",
        "Best late night food in {city}?",
        "Which {category} in {city} is worth the price?",
        "Where do I get the best sandwich in {city}?",
        "Good date night restaurant in {city}?",
        "Family friendly restaurants in {city}?",
    ],
    "nonprofit": [
        "What free coding programs are available for college students?",
        "Which nonprofits help students break into tech?",
        "Where can a low income student learn software engineering for free?",
        "What organizations offer free tech career training?",
        "Best free alternatives to a coding bootcamp?",
        "Which programs help underrepresented students get tech internships?",
        "What nonprofits partner with universities on computer science courses?",
        "How can I learn to code for free with real mentorship?",
        "Which organizations place students into tech jobs at no cost?",
        "Free computer science programs for first generation students?",
    ],
}

# If we don't have special questions for a category, reuse the generic ones so
# every business still gets 20 questions.
FALLBACK_EXTRA = [
    "Which {plural} in {city} do people recommend most?",
    "What's the highest rated {category} in {city}?",
    "Name a few {plural} in {city} worth visiting.",
    "Best {plural} near {city}?",
    "If you had to pick one {category} in {city}, which would it be?",
    "What {category} in {city} do you suggest for someone new to the area?",
    "Any well known {plural} in {city}?",
    "Which {category} in {city} stands out?",
    "Top rated {plural} in {city} right now?",
    "What should I know before choosing a {category} in {city}?",
]


def pluralize(word: str) -> str:
    """Rough plural. Good enough for category names like 'coffee shop' -> 'coffee shops'."""
    w = word.strip()
    if w.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    if w.endswith("y") and not w.endswith(("ay", "ey", "iy", "oy", "uy")):
        return w[:-1] + "ies"
    return w + "s"


def _pick_category_templates(category: str):
    """Find the extra question list that best matches the category text."""
    text = category.lower()
    for keyword, templates in CATEGORY_TEMPLATES.items():
        if keyword in text:
            return templates
    return FALLBACK_EXTRA


def build_questions(category: str, city: str, limit: int = 20):
    """
    Turn templates into real questions.

    category: what the business is, e.g. "coffee shop"
    city:     where it is, e.g. "Burlingame, CA"
    limit:    how many questions to return (default 20)

    Returns a list of question strings.
    """
    templates = GENERIC_TEMPLATES + _pick_category_templates(category)
    plural = pluralize(category)
    questions = [t.format(category=category, plural=plural, city=city) for t in templates]
    return questions[:limit]


if __name__ == "__main__":
    # Quick manual check: python src/questions.py
    for i, q in enumerate(build_questions("coffee shop", "Burlingame, CA"), 1):
        print(f"{i:2}. {q}")
