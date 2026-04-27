"""
eval_harness.py — Evaluation harness for the PawPal+ AI Scheduler.

Runs 4 predefined scheduling scenarios against the live Gemini API and
prints a results table showing pass/fail, confidence score, and a brief
diagnosis for each scenario.

Requires a Google AI Studio API key:
    set ANTHROPIC_API_KEY=AIza...        (Windows CMD)
    $env:ANTHROPIC_API_KEY="AIza..."     (PowerShell)

Run with:
    python test/eval_harness.py

Exit code 0 if all scenarios pass, 1 if any fail.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, time
from typing import List, Tuple

from pawpal_system import Owner, Pet, Task, TimeSlot
from ai_scheduler import run_agentic_schedule, compute_confidence

# ── Helpers ────────────────────────────────────────────────────────────────────

def _slot(start_h: int, duration: int) -> List[TimeSlot]:
    return [TimeSlot(start_time=time(start_h, 0), duration_minutes=duration)]


def _run(owner: Owner, tasks: List[Task], slots: List[TimeSlot], api_key: str):
    total = sum(s.duration_minutes for s in slots)
    schedule, agent_log = run_agentic_schedule(
        owner=owner,
        eligible_tasks=tasks,
        merged_slots=slots,
        schedule_date=date.today(),
        api_key=api_key,
    )
    confidence = compute_confidence(schedule, tasks, total_minutes=total)
    return schedule, agent_log, confidence, total


# ── Scenarios ──────────────────────────────────────────────────────────────────

def scenario_all_tasks_fit(api_key: str) -> Tuple[bool, str, float]:
    """
    90 min available, 3 tasks totalling 55 min.
    Expect: all HIGH tasks selected, total time ≤ 90, confidence ≥ 0.8.
    """
    owner = Owner(name="Jordan")
    pet   = Pet(name="Mochi", species="dog")
    pet.tasks = [
        Task(title="Give Mochi meds",  duration_minutes=10, priority="high",   start_time=time(9, 0)),
        Task(title="Morning walk",     duration_minutes=30, priority="medium",  start_time=time(9, 15)),
        Task(title="Play fetch",       duration_minutes=15, priority="low",     start_time=time(10, 0)),
    ]
    owner.add_pet(pet)

    schedule, _, confidence, total = _run(owner, pet.tasks, _slot(9, 90), api_key)

    high_ids = {t.id for t in pet.tasks if t.priority == "high"}
    high_covered = high_ids.issubset(set(schedule.selected_task_ids))
    time_ok      = schedule.total_time <= total

    passed = high_covered and time_ok and confidence >= 0.8
    notes  = []
    if not high_covered: notes.append("HIGH task missing")
    if not time_ok:      notes.append(f"time overflow ({schedule.total_time}>{total})")
    if confidence < 0.8: notes.append(f"low confidence ({confidence:.2f})")
    return passed, "; ".join(notes) or "all checks passed", confidence


def scenario_high_never_skipped(api_key: str) -> Tuple[bool, str, float]:
    """
    20 min available. HIGH task = 10 min, LOW task = 25 min (won't fit).
    Expect: HIGH task selected, LOW dropped, confidence ≥ 0.6.
    """
    owner = Owner(name="Sarah")
    pet   = Pet(name="Whiskers", species="cat")
    pet.tasks = [
        Task(title="Give Whiskers meds", duration_minutes=10, priority="high"),
        Task(title="Play with Whiskers", duration_minutes=25, priority="low"),
    ]
    owner.add_pet(pet)

    schedule, _, confidence, total = _run(owner, pet.tasks, _slot(9, 20), api_key)

    meds_id      = pet.tasks[0].id
    high_covered = meds_id in schedule.selected_task_ids
    time_ok      = schedule.total_time <= total

    passed = high_covered and time_ok and confidence >= 0.6
    notes  = []
    if not high_covered: notes.append("HIGH meds task was skipped")
    if not time_ok:      notes.append(f"time overflow ({schedule.total_time}>{total})")
    if confidence < 0.6: notes.append(f"low confidence ({confidence:.2f})")
    return passed, "; ".join(notes) or "all checks passed", confidence


def scenario_multi_pet_same_name(api_key: str) -> Tuple[bool, str, float]:
    """
    Two pets each have a HIGH task called 'Morning Walk'.
    Expect: both tasks selected (tests numbered-task disambiguation), confidence ≥ 0.8.
    """
    owner = Owner(name="Alex")

    dog = Pet(name="Buddy", species="dog")
    dog.tasks = [
        Task(title="Morning Walk", duration_minutes=20, priority="high", start_time=time(9, 0)),
    ]

    cat = Pet(name="Luna", species="cat")
    cat.tasks = [
        Task(title="Morning Walk", duration_minutes=10, priority="high", start_time=time(9, 30)),
    ]

    owner.add_pet(dog)
    owner.add_pet(cat)
    all_tasks = dog.tasks + cat.tasks

    schedule, _, confidence, total = _run(owner, all_tasks, _slot(9, 60), api_key)

    both_selected = all(t.id in schedule.selected_task_ids for t in all_tasks)
    time_ok       = schedule.total_time <= total

    passed = both_selected and time_ok and confidence >= 0.8
    notes  = []
    if not both_selected:
        selected_count = sum(1 for t in all_tasks if t.id in schedule.selected_task_ids)
        notes.append(f"only {selected_count}/2 same-named HIGH tasks selected")
    if not time_ok: notes.append(f"time overflow ({schedule.total_time}>{total})")
    if confidence < 0.8: notes.append(f"low confidence ({confidence:.2f})")
    return passed, "; ".join(notes) or "all checks passed", confidence


def scenario_self_critique_fires(api_key: str) -> Tuple[bool, str, float]:
    """
    Two HIGH tasks both fit (10 + 15 = 25 min) in a 30-min slot.
    Expect: both HIGH tasks selected after at most 3 iterations, confidence ≥ 0.6.
    This scenario is most likely to trigger the self-critique loop.
    """
    owner = Owner(name="Kim")
    pet   = Pet(name="Rex", species="dog")
    pet.tasks = [
        Task(title="Give Rex meds",   duration_minutes=10, priority="high", start_time=time(9, 0)),
        Task(title="Short walk",      duration_minutes=15, priority="high", start_time=time(9, 15)),
        Task(title="Brush coat",      duration_minutes=20, priority="low",  start_time=time(9, 35)),
    ]
    owner.add_pet(pet)

    schedule, agent_log, confidence, total = _run(owner, pet.tasks, _slot(9, 30), api_key)

    high_ids     = {t.id for t in pet.tasks if t.priority == "high"}
    high_covered = high_ids.issubset(set(schedule.selected_task_ids))
    time_ok      = schedule.total_time <= total
    iterations   = sum(1 for e in agent_log if e["step"].startswith("Agent — Iteration"))

    passed = high_covered and time_ok and confidence >= 0.6
    notes  = []
    if not high_covered: notes.append("not all HIGH tasks selected")
    if not time_ok:      notes.append(f"time overflow ({schedule.total_time}>{total})")
    if confidence < 0.6: notes.append(f"low confidence ({confidence:.2f})")
    notes.append(f"used {iterations} iteration(s)")
    return passed, "; ".join(notes) if not passed else f"all checks passed ({iterations} iteration(s))", confidence


# ── Runner ─────────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("Scenario 1 — All tasks fit",               scenario_all_tasks_fit),
    ("Scenario 2 — HIGH task must not be skipped", scenario_high_never_skipped),
    ("Scenario 3 — Multi-pet same-name tasks",   scenario_multi_pet_same_name),
    ("Scenario 4 — Self-critique loop fires",    scenario_self_critique_fires),
]

WIDTH = 60

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.")
        print("  PowerShell:  $env:ANTHROPIC_API_KEY=\"AIza...\"")
        print("  CMD:         set ANTHROPIC_API_KEY=AIza...")
        sys.exit(1)

    print()
    print("PawPal+ AI Evaluation Harness")
    print("=" * WIDTH)

    results = []
    for name, fn in SCENARIOS:
        print(f"\n{name}")
        print("-" * WIDTH)
        try:
            passed, notes, confidence = fn(api_key)
        except Exception as exc:
            passed, notes, confidence = False, f"ERROR: {exc}", 0.0

        status = "PASS" if passed else "FAIL"
        print(f"  Result     : {'✅' if passed else '❌'} {status}")
        print(f"  Confidence : {confidence:.0%}")
        print(f"  Notes      : {notes}")
        results.append((name, passed, confidence))

    # ── Summary table ──────────────────────────────────────────────────────────
    print()
    print("=" * WIDTH)
    passed_count = sum(1 for _, p, _ in results if p)
    avg_conf     = sum(c for _, _, c in results) / len(results)
    print(f"Summary: {passed_count}/{len(results)} passed   |   "
          f"Avg confidence: {avg_conf:.0%}")
    print("=" * WIDTH)
    print()

    for name, passed, confidence in results:
        mark = "✅" if passed else "❌"
        print(f"  {mark}  {name:<48}  {confidence:.0%}")

    print()
    sys.exit(0 if passed_count == len(results) else 1)


if __name__ == "__main__":
    main()
