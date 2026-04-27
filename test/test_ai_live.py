"""
test_ai_live.py — Live integration smoke test for the agentic scheduler.

Requires a real Anthropic API key:
    set ANTHROPIC_API_KEY=sk-ant-...      (Windows CMD)
    $env:ANTHROPIC_API_KEY="sk-ant-..."   (PowerShell)

Run with:
    python -m pytest test/test_ai_live.py -v -s

Skipped automatically if ANTHROPIC_API_KEY is not set.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import date, time

from pawpal_system import Owner, Pet, Task, TimeSlot
from ai_scheduler import run_agentic_schedule, compute_confidence

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
needs_key = pytest.mark.skipif(not API_KEY, reason="ANTHROPIC_API_KEY not set")


@needs_key
def test_ai_scheduler_returns_valid_schedule():
    """
    Full end-to-end smoke test: Claude receives a real scheduling context,
    runs the agentic loop, and returns a populated Schedule object.
    """
    owner = Owner(name="Jordan")
    pet = Pet(name="Mochi", species="dog")
    pet.tasks = [
        Task(title="Give Mochi meds", duration_minutes=10, priority="high",
             start_time=time(9, 0)),
        Task(title="Morning walk",    duration_minutes=30, priority="medium",
             start_time=time(9, 15)),
        Task(title="Play fetch",      duration_minutes=15, priority="low",
             start_time=time(10, 0)),
    ]
    owner.add_pet(pet)
    slots = [TimeSlot(start_time=time(9, 0), duration_minutes=60)]

    schedule, agent_log = run_agentic_schedule(
        owner=owner,
        eligible_tasks=pet.tasks,
        merged_slots=slots,
        schedule_date=date.today(),
        api_key=API_KEY,
    )

    # ── Basic structure checks ──────────────────────────────────────────────
    assert schedule is not None,                   "Schedule should not be None"
    assert len(schedule.selected_task_ids) > 0,    "At least one task should be selected"
    assert schedule.total_time > 0,                "Total time should be > 0"
    assert schedule.explanation.startswith("[AI]"), "Explanation should be AI-generated"
    assert len(agent_log) >= 3,                    "Log should have RAG + ≥1 iteration + final"

    # ── HIGH task must be included ──────────────────────────────────────────
    meds_task = pet.tasks[0]
    assert meds_task.id in schedule.selected_task_ids, \
        "HIGH-priority 'Give Mochi meds' must be selected"

    # ── Time constraint respected ───────────────────────────────────────────
    assert schedule.total_time <= 60, \
        f"Total time {schedule.total_time} min exceeds available 60 min"

    # ── Confidence score is meaningful ──────────────────────────────────────
    score = compute_confidence(schedule, pet.tasks, total_minutes=60)
    assert 0.0 <= score <= 1.0, f"Score {score} out of range"
    assert score >= 0.6,        f"Score {score} too low — HIGH task may have been missed"

    print(f"\n  Tasks selected : {len(schedule.selected_task_ids)}")
    print(f"  Time used      : {schedule.total_time}/60 min")
    print(f"  Confidence     : {score:.0%}")
    print(f"  Explanation    : {schedule.explanation}")
    print(f"  Agent steps    : {len(agent_log)}")
    for entry in agent_log:
        print(f"    [{entry['step']}]")


@needs_key
def test_ai_scheduler_high_task_never_skipped_when_fits():
    """
    When time is tight but a HIGH task fits, the agentic loop must include it.
    Verifies that the self-critique catches any miss and forces a revision.
    """
    owner = Owner(name="Sarah")
    pet = Pet(name="Whiskers", species="cat")
    pet.tasks = [
        Task(title="Give Whiskers meds", duration_minutes=5,  priority="high"),
        Task(title="Play with Whiskers", duration_minutes=25, priority="low"),
    ]
    owner.add_pet(pet)
    # 30 min total — both tasks fit (5 + 25 = 30), HIGH must be included
    slots = [TimeSlot(start_time=time(9, 0), duration_minutes=30)]

    schedule, _ = run_agentic_schedule(
        owner=owner,
        eligible_tasks=pet.tasks,
        merged_slots=slots,
        schedule_date=date.today(),
        api_key=API_KEY,
    )

    meds_id = pet.tasks[0].id
    assert meds_id in schedule.selected_task_ids, \
        "HIGH-priority meds task must be selected — self-critique should have enforced this"
