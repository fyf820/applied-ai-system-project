"""
test_ai_components.py — Tests for the AI-specific components added in the final extension.

Coverage:
  1. RAG Retriever    (pet_care_kb.py)   — 4 tests  (no API key needed)
  2. Self-Critique    (ai_scheduler.py)  — 4 tests  (no API key needed)
  3. Task Matching    (ai_scheduler.py)  — 4 tests  (no API key needed)
  4. Confidence Score (ai_scheduler.py)  — 2 tests  (no API key needed)

All tests are deterministic — they exercise pure-Python logic and never call
the Anthropic API.  Tests in groups 2–4 are skipped automatically if the
`anthropic` package is not installed.

Run with:
    python -m pytest test/test_ai_components.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import time

from pawpal_system import Pet, Task, Schedule, TimeSlot
from pet_care_kb import retrieve

# ai_scheduler helpers are pure functions — no API call happens when we import them.
# We skip their tests gracefully if the `anthropic` package isn't installed yet.
try:
    from ai_scheduler import _self_critique, _match_task, compute_confidence
    _AI_IMPORTS_OK = True
except ImportError:
    _AI_IMPORTS_OK = False

needs_ai = pytest.mark.skipif(
    not _AI_IMPORTS_OK,
    reason="anthropic package not installed — run `pip install anthropic`",
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slot(minutes: int) -> list:
    """Return a single TimeSlot of `minutes` length starting at 09:00."""
    return [TimeSlot(start_time=time(9, 0), duration_minutes=minutes)]


# ═════════════════════════════════════════════════════════════════════════════
# 1. RAG RETRIEVAL TESTS
#    Prove that the TF-IDF retriever surfaces relevant guidelines for a given
#    scheduling context.  No network or API calls involved.
# ═════════════════════════════════════════════════════════════════════════════

def test_medication_query_retrieves_medication_guideline():
    """
    When a task title includes 'meds', the medication guideline
    ('medications must never be skipped') should appear in the top-4 results.
    """
    pet = Pet(name="Mochi", species="dog")
    pet.tasks = [Task(title="Give Mochi meds", duration_minutes=5, priority="high")]

    results = retrieve("schedule for Mochi", [pet], top_k=4)

    assert any("medication" in r.lower() or "dose" in r.lower() for r in results), (
        f"Expected medication guideline in top-4. Got:\n" + "\n".join(results)
    )


def test_dog_walk_query_retrieves_exercise_guideline():
    """
    A dog with a walk task should surface the exercise/activity guideline.
    """
    pet = Pet(name="Buddy", species="dog")
    pet.tasks = [Task(title="Morning walk", duration_minutes=30, priority="high")]

    results = retrieve("schedule for Buddy", [pet], top_k=4)

    assert any("exercise" in r.lower() or "walk" in r.lower() for r in results), (
        f"Expected exercise guideline in top-4. Got:\n" + "\n".join(results)
    )


def test_retrieve_returns_exactly_top_k_results():
    """retrieve(top_k=3) must return exactly 3 documents."""
    pet = Pet(name="Whiskers", species="cat")
    results = retrieve("cat feeding schedule", [pet], top_k=3)
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"


def test_retrieve_no_duplicate_documents():
    """
    No two entries in the result list should be identical.
    Duplicates would waste prompt tokens and indicate a scoring bug.
    """
    pet = Pet(name="Mochi", species="dog")
    results = retrieve("scheduling for dog", [pet], top_k=4)
    assert len(results) == len(set(results)), (
        "Duplicate guidelines returned — each result must be unique."
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2. SELF-CRITIQUE TESTS
#    Prove that the rule-based checker correctly approves good schedules and
#    flags real problems (skipped HIGH tasks, unresolved model concerns).
# ═════════════════════════════════════════════════════════════════════════════

@needs_ai
def test_critique_ok_when_all_high_tasks_are_included():
    """
    When every HIGH-priority task is selected, self-critique must return 'OK'.
    This is the happy path — no revision needed.
    """
    tasks = [
        Task(title="Give meds", duration_minutes=10, priority="high"),
        Task(title="Walk",      duration_minutes=20, priority="medium"),
    ]
    result = _self_critique(tasks, "None", tasks, _slot(60))
    assert result == "OK", f"Expected 'OK', got: {result}"


@needs_ai
def test_critique_flags_skipped_high_task_that_fits():
    """
    If a HIGH task was skipped but the remaining time is enough to include it,
    the critique must name that task so Claude can add it in the next iteration.
    """
    tasks = [
        Task(title="Give meds", duration_minutes=10, priority="high"),
        Task(title="Walk",      duration_minutes=20, priority="medium"),
    ]
    walk_task = tasks[1]
    # Only "Walk" selected — "Give meds" skipped despite 60 min available
    result = _self_critique([walk_task], "None", tasks, _slot(60))

    assert result != "OK", "Critique should have flagged the skipped HIGH task"
    assert "Give meds" in result, f"Expected task name in critique. Got: {result}"


@needs_ai
def test_critique_ok_when_high_task_genuinely_cannot_fit():
    """
    When a HIGH task is longer than the total available time, it is impossible
    to include — the critique should NOT flag it (no false alarm).
    """
    tasks = [Task(title="Long walk", duration_minutes=60, priority="high")]
    # Only 10 min available — task truly can't fit
    result = _self_critique([], "None", tasks, _slot(10))  # no tasks selected
    assert result == "OK", (
        f"Should not flag a HIGH task that cannot fit. Got: {result}"
    )


@needs_ai
def test_critique_surfaces_unresolved_model_concerns():
    """
    When Claude itself reports a concern (non-'None' CONCERNS field),
    the critique must include that concern so it is addressed in the next round.
    """
    tasks = [Task(title="Feed cat", duration_minutes=5, priority="medium")]
    # Concern explicitly mentions a HIGH-priority issue — must be surfaced.
    result = _self_critique(
        tasks,
        "Morning walk (HIGH priority) may conflict with feeding at 09:00",
        tasks,
        _slot(60),
    )
    assert "high" in result.lower(), (
        f"Expected HIGH-related concern to be surfaced. Got: {result}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# 3. TASK MATCHING TESTS
#    Prove that _match_task() can map Claude's text output back to the correct
#    Task object even when Claude paraphrases or abbreviates the title.
# ═════════════════════════════════════════════════════════════════════════════

@needs_ai
def test_match_exact_title():
    """Exact title match must always succeed."""
    tasks = [Task(title="Walk Mochi", duration_minutes=30, priority="high")]
    matched = _match_task("Walk Mochi", tasks)
    assert matched is not None
    assert matched.title == "Walk Mochi"


@needs_ai
def test_match_returns_correct_task_among_multiple():
    """With two tasks, the matcher must pick the right one."""
    tasks = [
        Task(title="Walk Mochi",      duration_minutes=30, priority="high"),
        Task(title="Feed Whiskers",   duration_minutes=10, priority="high"),
    ]
    assert _match_task("Walk Mochi",    tasks).title == "Walk Mochi"
    assert _match_task("Feed Whiskers", tasks).title == "Feed Whiskers"


@needs_ai
def test_match_word_overlap_handles_paraphrasing():
    """
    Claude sometimes shortens titles (e.g. 'Mochi meds' for 'Give Mochi meds').
    The word-overlap fallback should still find the correct task.
    """
    tasks = [Task(title="Give Mochi meds", duration_minutes=5, priority="high")]
    matched = _match_task("Mochi meds", tasks)
    assert matched is not None, "Word-overlap match should find 'Give Mochi meds'"


@needs_ai
def test_match_unrelated_title_returns_none():
    """
    A title with no overlap to any task must return None.
    This prevents hallucinated task names from corrupting the schedule.
    """
    tasks = [Task(title="Walk Mochi", duration_minutes=30, priority="high")]
    assert _match_task("xyz", tasks) is None, (
        "Completely unrelated title should return None"
    )


# ═════════════════════════════════════════════════════════════════════════════
# 4. CONFIDENCE SCORE TESTS
#    Prove that compute_confidence() correctly rewards full HIGH-task coverage
#    and penalises schedules that miss critical tasks.
# ═════════════════════════════════════════════════════════════════════════════

@needs_ai
def test_confidence_is_1_when_schedule_is_perfect():
    """
    When all HIGH tasks are selected and all available time is used,
    the confidence score must be 1.0 (maximum).
    """
    task = Task(title="Give meds", duration_minutes=30, priority="high")
    sched = Schedule(date="2026-04-26", owner_id="owner-1")
    sched.selected_task_ids = [task.id]
    sched.total_time = 30

    score = compute_confidence(sched, [task], total_minutes=30)
    assert score == 1.0, f"Expected 1.0 for perfect schedule, got {score}"


@needs_ai
def test_confidence_below_0_6_when_high_task_skipped():
    """
    Skipping a HIGH-priority task reduces the HIGH-coverage component to 0,
    which should drag the overall score below 0.6.
    """
    high_task = Task(title="Give meds", duration_minutes=10, priority="high")
    med_task  = Task(title="Walk",      duration_minutes=20, priority="medium")

    sched = Schedule(date="2026-04-26", owner_id="owner-1")
    sched.selected_task_ids = [med_task.id]   # meds were skipped
    sched.total_time = 20

    score = compute_confidence(sched, [high_task, med_task], total_minutes=60)
    assert score < 0.6, (
        f"Skipping HIGH task should score below 0.6, got {score}"
    )
