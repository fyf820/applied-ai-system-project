"""
pet_care_kb.py — Pet Care Knowledge Base (RAG component)

Stores expert pet-care guidelines as a small in-memory corpus.
retrieve() scores each document against the current scheduling context
using TF-IDF + tag-match bonus, then returns the top-k content strings
to inject into Claude's prompt as retrieved context.

No external vector-store dependency required.
"""

import math
import logging
from collections import Counter
from typing import List

logger = logging.getLogger(__name__)

# ── Knowledge base ────────────────────────────────────────────────────────────
# Each entry has:
#   id      – unique identifier (for logging / debugging)
#   tags    – short keyword list used for fast matching
#   content – the text injected into Claude's prompt
KNOWLEDGE_BASE = [
    {
        "id": "dog_exercise",
        "tags": ["dog", "walk", "exercise", "run", "activity", "outdoor"],
        "content": (
            "Dogs need 30–60 min of exercise daily; active breeds (Labrador, Husky, "
            "Border Collie) need 90+ min. Morning walks regulate energy for the rest of "
            "the day and should be treated as HIGH priority."
        ),
    },
    {
        "id": "cat_feeding",
        "tags": ["cat", "feed", "meal", "food", "eat", "feeding"],
        "content": (
            "Cats should be fed 2–3 times per day at consistent times. "
            "Skipping meals disrupts metabolism and can cause hepatic lipidosis. "
            "Feeding tasks are HIGH priority."
        ),
    },
    {
        "id": "dog_feeding",
        "tags": ["dog", "feed", "meal", "food", "eat", "feeding"],
        "content": (
            "Adult dogs thrive on 2 meals per day (morning and evening). "
            "Irregular feeding causes digestive upset; never skip a feeding task. "
            "Mark feeding as HIGH priority."
        ),
    },
    {
        "id": "medication",
        "tags": ["med", "meds", "medicine", "pill", "vaccine", "medication", "treatment", "drug"],
        "content": (
            "Medications must be given at consistent times and are always the HIGHEST priority "
            "on any schedule. Missing a dose can be medically serious and should never be skipped "
            "regardless of time constraints."
        ),
    },
    {
        "id": "cat_grooming",
        "tags": ["cat", "groom", "brush", "grooming", "trim", "hair", "fur"],
        "content": (
            "Long-haired cats need daily brushing to prevent matting; short-haired cats weekly. "
            "Regular grooming reduces hairballs and is a low-stress bonding activity. "
            "Schedule grooming as MEDIUM priority."
        ),
    },
    {
        "id": "dog_grooming",
        "tags": ["dog", "groom", "brush", "bath", "grooming", "nail", "trim", "fur"],
        "content": (
            "Short-haired dogs need weekly brushing; long-haired daily. "
            "Bathe every 4–6 weeks; trim nails every 3–4 weeks to prevent joint stress. "
            "Grooming is MEDIUM priority."
        ),
    },
    {
        "id": "play_enrichment",
        "tags": ["play", "toy", "fetch", "game", "enrichment", "training", "interactive"],
        "content": (
            "15–30 min of interactive play daily reduces anxiety and destructive behaviour "
            "for both dogs and cats. Schedule play after meals or walks, never just before "
            "feeding. Play is LOW-to-MEDIUM priority."
        ),
    },
    {
        "id": "scheduling_principles",
        "tags": ["schedule", "priority", "high", "routine", "consistency", "plan", "daily"],
        "content": (
            "Always schedule HIGH-priority tasks first. Pets benefit most from consistent "
            "daily routines — same tasks at the same times reduce stress and improve training "
            "outcomes. Never skip HIGH tasks if they fit within the available time."
        ),
    },
    {
        "id": "multiple_pets",
        "tags": ["multiple", "pets", "dog", "cat", "several", "prioritize", "two", "both"],
        "content": (
            "When scheduling for multiple pets, prioritise health-critical tasks (medications, "
            "meals) for any pet before lower-priority enrichment tasks for others. "
            "Shared care windows can be batched if tasks are compatible."
        ),
    },
    {
        "id": "time_management",
        "tags": ["time", "slot", "available", "busy", "limited", "fit", "tight", "constraint"],
        "content": (
            "If total task time exceeds available slots, drop LOW-priority tasks first, "
            "then MEDIUM. Never drop HIGH-priority tasks unless there is literally no time. "
            "Consider splitting long tasks if the owner has multiple short windows."
        ),
    },
]

# Pre-tokenise all documents once at import time for efficiency
_DOC_TOKENS: List[List[str]] = [
    list(set(entry["tags"]) | set(entry["content"].lower().split()))
    for entry in KNOWLEDGE_BASE
]


def retrieve(query: str, pets: list, top_k: int = 4) -> List[str]:
    """
    Return the top_k most relevant care-guideline strings for the current
    scheduling context (query text + pet info).

    Scoring:
      - TF-IDF relevance between query tokens and each document
      - Extra bonus for direct tag matches (tag_hits * 0.8)

    Args:
        query:  Free-text description of the scheduling context.
        pets:   List of Pet objects (species + task titles expand the query).
        top_k:  Number of documents to return.

    Returns:
        List of content strings ready to inject into a prompt.
    """
    # Build a rich query token set from the text + pet context
    q_tokens: set = set(query.lower().split())
    for pet in pets:
        q_tokens.add(pet.species.lower())
        for task in getattr(pet, "tasks", []):
            q_tokens.update(task.title.lower().split())

    N = len(KNOWLEDGE_BASE)
    scored: List[tuple] = []

    for i, entry in enumerate(KNOWLEDGE_BASE):
        doc_tokens = _DOC_TOKENS[i]
        tf_counter = Counter(doc_tokens)
        doc_len = len(doc_tokens) or 1

        # TF-IDF score
        tfidf = 0.0
        for token in q_tokens:
            tf_val = tf_counter.get(token, 0) / doc_len
            df = sum(1 for d in _DOC_TOKENS if token in d)
            idf = math.log((N + 1) / (df + 1)) + 1
            tfidf += tf_val * idf

        # Tag-match bonus
        tag_hits = len(q_tokens & set(entry["tags"]))
        total_score = tfidf + tag_hits * 0.8

        scored.append((total_score, entry["id"], entry["content"]))

    scored.sort(reverse=True)
    top = [content for _, _, content in scored[:top_k]]

    logger.debug(
        "[RAG] Top-%d docs for query '%s…': %s",
        top_k,
        query[:60],
        [eid for _, eid, _ in scored[:top_k]],
    )
    return top
