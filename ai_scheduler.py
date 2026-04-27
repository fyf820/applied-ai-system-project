"""
ai_scheduler.py — Agentic AI Scheduler for PawPal+

Combines RAG (pet-care knowledge retrieval) with an agentic loop:
  1. RAG       — retrieve relevant care guidelines from pet_care_kb
  2. Draft     — Gemini proposes a schedule with reasoning
  3. Critique  — rule-based checker verifies HIGH-priority coverage
  4. Revise    — Gemini refines if critique found issues (up to MAX_ITERATIONS)
  5. Build     — parse Gemini's final answer into a Schedule object

All steps are logged to pawpal.log and returned as an agent_log list
for display in the Streamlit UI.
"""

import logging
import os
from datetime import date, time
from typing import Dict, List, Optional, Tuple

from google import genai

from pawpal_system import Owner, Pet, Task, Schedule, TimeSlot
from pet_care_kb import retrieve

# ── Logging setup ─────────────────────────────────────────────────────────────
# Runs once when the module is first imported.
# Writes INFO+ to pawpal.log; WARNING+ to the console.
if not logging.root.handlers:
    _log_path = os.path.join(os.path.dirname(__file__), "pawpal.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(_log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3          # Hard cap on agentic refinement rounds
_MODEL = "gemini-2.0-flash"            # Free on Google AI Studio

# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_time(t: time) -> str:
    return t.strftime("%H:%M")


def _fmt_slots(slots: List[TimeSlot]) -> str:
    parts = []
    for s in slots:
        total_end = s.start_time.hour * 60 + s.start_time.minute + s.duration_minutes
        end_t = time(total_end // 60 % 24, total_end % 60)
        parts.append(
            f"{_fmt_time(s.start_time)}–{_fmt_time(end_t)} ({s.duration_minutes} min)"
        )
    return ", ".join(parts) if parts else "none"


def _fmt_tasks(tasks: List[Task]) -> str:
    lines = []
    for t in tasks:
        time_str = _fmt_time(t.start_time) if t.start_time else "flexible"
        recur = f" [{t.frequency}]" if t.frequency else ""
        lines.append(
            f"    • [{t.priority.upper()}] {t.title}: "
            f"{t.duration_minutes} min @ {time_str}{recur}"
        )
    return "\n".join(lines) if lines else "    (none)"


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_field(text: str, field: str):
    """
    Extract the value after 'FIELD:' from Claude's response.
    Returns a list for SELECTED TASKS, a string for all other fields.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith(field.upper() + ":"):
            value = stripped.split(":", 1)[1].strip()
            if field == "SELECTED TASKS":
                return [t.strip() for t in value.split(",") if t.strip()]
            return value
    return [] if field == "SELECTED TASKS" else ""


def _match_task(title: str, eligible_tasks: List[Task]) -> Optional[Task]:
    """
    Find the best-matching Task for a title string returned by Claude.
    Tries substring containment first, then falls back to word-overlap.
    """
    tl = title.strip().lower()
    tl_words = set(tl.split())

    # 1. Substring match (most reliable)
    for t in eligible_tasks:
        task_lower = t.title.lower()
        if tl in task_lower or task_lower in tl:
            return t

    # 2. Word-overlap fallback (handles paraphrasing)
    best_score = 0
    best_task = None
    for t in eligible_tasks:
        task_words = set(t.title.lower().split())
        overlap = len(tl_words & task_words)
        if overlap > best_score:
            best_score = overlap
            best_task = t

    return best_task if best_score >= 1 else None


# ── Self-critique ─────────────────────────────────────────────────────────────

def _self_critique(
    selected_tasks: List[Task],
    concerns: str,
    eligible_tasks: List[Task],
    merged_slots: List[TimeSlot],
) -> str:
    """
    Rule-based checker that validates Claude's proposed schedule.

    Accepts a list of already-resolved Task objects (not titles), so there is
    no ambiguity when multiple pets share a task name.

    Checks:
      - Any HIGH-priority task skipped that could still fit?
      - Did Claude itself flag unresolved concerns?

    Returns 'OK' if the schedule passes, or a critique string to feed
    back to Claude for revision.
    """
    total_minutes = sum(s.duration_minutes for s in merged_slots)

    selected_ids = {t.id for t in selected_tasks}
    used = sum(t.duration_minutes for t in selected_tasks)
    remaining = max(total_minutes - used, 0)

    issues = []

    for task in eligible_tasks:
        if task.priority != "high":
            continue
        if task.id not in selected_ids and task.duration_minutes <= remaining:
            issues.append(
                f"HIGH-priority task '{task.title}' ({task.duration_minutes} min) "
                f"was skipped but {remaining} min remain — please include it "
                f"(task number in the list above)."
            )

    # Surface any concerns the model itself flagged
    clean = concerns.strip().lower()
    if clean and clean not in ("none", "none.", "no concerns", "no concerns.", "n/a", "n/a."):
        issues.append(f"Model flagged: {concerns}")

    result = "; ".join(issues) if issues else "OK"
    logger.info("[Critique] %s", result)
    return result


# ── Confidence scoring ───────────────────────────────────────────────────────

def compute_confidence(
    schedule: Schedule,
    eligible_tasks: List[Task],
    total_minutes: int,
) -> float:
    """
    Score how well a generated schedule covers critical tasks and uses time.

    Formula (weights reflect that missing HIGH tasks is worse than idle time):
        0.6 × (HIGH tasks selected / total HIGH tasks)   <- priority coverage
      + 0.4 × (time used / total available minutes)      <- time efficiency

    Returns a float in [0.0, 1.0] rounded to 2 decimal places.
    A score of 1.0 means all HIGH tasks were included and all time was filled.
    """
    high_tasks = [t for t in eligible_tasks if t.priority == "high"]
    selected_ids = set(schedule.selected_task_ids)

    if high_tasks:
        high_coverage = sum(1 for t in high_tasks if t.id in selected_ids) / len(high_tasks)
    else:
        high_coverage = 1.0  # no HIGH tasks → coverage is perfect by definition

    time_efficiency = (
        min(schedule.total_time / total_minutes, 1.0) if total_minutes > 0 else 0.0
    )

    score = round(0.6 * high_coverage + 0.4 * time_efficiency, 2)
    logger.info(
        "[Confidence] %.2f  (HIGH coverage=%.2f, time efficiency=%.2f)",
        score, high_coverage, time_efficiency,
    )
    return score


# ── Main entry point ──────────────────────────────────────────────────────────

def run_agentic_schedule(
    owner: Owner,
    eligible_tasks: List[Task],
    merged_slots: List[TimeSlot],
    schedule_date: date,
    api_key: str,
) -> Tuple[Schedule, List[Dict]]:
    """
    Run the full agentic scheduling pipeline.

    Args:
        owner:           The pet owner (name, preferences, pets).
        eligible_tasks:  Tasks that fall on schedule_date.
        merged_slots:    Owner's merged available time slots.
        schedule_date:   The date being scheduled.
        api_key:         Google AI Studio API key.

    Returns:
        schedule   – Schedule object populated by the agent.
        agent_log  – List of {"step": str, "content": str} dicts for UI display.
    """
    logger.info(
        "[Agent] Starting for %s on %s (%d tasks, %d min available)",
        owner.name,
        schedule_date,
        len(eligible_tasks),
        sum(s.duration_minutes for s in merged_slots),
    )

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(model=_MODEL)
    agent_log: List[Dict] = []

    # ── Step 1: RAG retrieval ─────────────────────────────────────────────────
    rag_query = (
        "pet care scheduling for "
        + " and ".join(
            f"{p.name} ({p.species})" for p in owner.get_pets()
        )
    )
    retrieved = retrieve(rag_query, owner.get_pets(), top_k=4)
    rag_block = "\n".join(f"  • {doc}" for doc in retrieved)

    logger.info("[RAG] Retrieved %d guidelines", len(retrieved))
    agent_log.append({
        "step": "RAG — Retrieved Care Guidelines",
        "content": rag_block,
    })

    # ── Build scheduling context (shared across all iterations) ──────────────
    total_minutes = sum(s.duration_minutes for s in merged_slots)

    # Number every eligible task so the model can reference tasks by index,
    # eliminating all ambiguity when multiple pets share a task name.
    task_index: Dict[int, Task] = {}
    task_id_set = {t.id for t in eligible_tasks}
    numbered_lines: List[str] = []
    num = 1
    for pet in owner.get_pets():
        pet_tasks = [t for t in pet.tasks if t.id in task_id_set]
        for t in pet_tasks:
            time_str = _fmt_time(t.start_time) if t.start_time else "flexible"
            recur = f" [{t.frequency}]" if t.frequency else ""
            numbered_lines.append(
                f"  [{num}] [{t.priority.upper()}] {t.title} "
                f"({pet.name}, {pet.species}): "
                f"{t.duration_minutes} min @ {time_str}{recur}"
            )
            task_index[num] = t
            num += 1

    tasks_block = "\n".join(numbered_lines) if numbered_lines else "  (none)"

    context = (
        "You are an expert pet care scheduling assistant.\n\n"
        "## Relevant Care Guidelines (retrieved knowledge)\n"
        f"{rag_block}\n\n"
        "## Scheduling Context\n"
        f"Owner: {owner.name}\n"
        f"Date: {schedule_date.strftime('%A, %Y-%m-%d')}\n"
        f"Available time: {_fmt_slots(merged_slots)} (total {total_minutes} min)\n"
        f"Preferred tasks: "
        f"{', '.join(owner.preferences.get('preferred_tasks', [])) or 'none'}\n"
        f"Preferred pets:  "
        f"{', '.join(owner.preferences.get('preferred_pets', [])) or 'none'}\n\n"
        "## Tasks to Consider (each has a unique number)\n"
        + tasks_block
    )

    REPLY_FORMAT = (
        "Respond in EXACTLY this format (no extra text):\n"
        "SELECTED TASKS: <comma-separated task numbers, e.g. 1, 3, 5>\n"
        "REASONING: <2–3 sentences referencing the care guidelines above>\n"
        "CONCERNS: <issues such as conflicts or skipped high-priority tasks — or 'None'>"
    )

    # ── Step 2: Agentic iteration loop ────────────────────────────────────────
    prev_selected_nums: List[int] = []
    prev_reasoning = ""
    prev_concerns = ""
    critique = ""

    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info("[Agent] Iteration %d/%d", iteration, MAX_ITERATIONS)

        if iteration == 1:
            user_msg = (
                context + "\n\n"
                "## Instructions\n"
                "Select which tasks to include in today's schedule. Rules:\n"
                "1. HIGH-priority tasks MUST be included if they fit — never skip them.\n"
                "2. Fill remaining time with MEDIUM, then LOW priority tasks.\n"
                "3. Do not select tasks whose time windows overlap each other.\n"
                "4. Reference the care guidelines in your reasoning.\n"
                "5. Use the task numbers (e.g. 1, 3) in SELECTED TASKS — not titles.\n\n"
                + REPLY_FORMAT
            )
        else:
            prev_nums_str = ", ".join(str(n) for n in prev_selected_nums)
            user_msg = (
                f"Iteration {iteration}: Revise your schedule based on this critique:\n"
                f"  {critique}\n\n"
                f"Your previous answer:\n"
                f"  SELECTED TASKS: {prev_nums_str}\n"
                f"  REASONING: {prev_reasoning}\n"
                f"  CONCERNS: {prev_concerns}\n\n"
                + REPLY_FORMAT
            )

        try:
            response = chat.send_message(user_msg)
            reply = response.text
        except Exception as exc:
            logger.error("[Agent] API error on iteration %d: %s", iteration, exc)
            agent_log.append({
                "step": f"Iteration {iteration} — API Error",
                "content": str(exc),
            })
            break
        logger.info("[Agent] Iteration %d reply:\n%s", iteration, reply)
        agent_log.append({
            "step": f"Agent — Iteration {iteration}",
            "content": reply,
        })

        # Parse task numbers from "SELECTED TASKS: 1, 3, 5"
        raw_nums = _parse_field(reply, "SELECTED TASKS")
        prev_selected_nums = []
        for token in (raw_nums if isinstance(raw_nums, list) else []):
            try:
                n = int(token.strip())
                if n in task_index:
                    prev_selected_nums.append(n)
            except ValueError:
                pass

        prev_reasoning = _parse_field(reply, "REASONING")
        prev_concerns = _parse_field(reply, "CONCERNS")

        # Resolve numbers to Task objects for the self-critique
        selected_tasks_for_critique = [
            task_index[n] for n in prev_selected_nums if n in task_index
        ]

        # ── Self-critique ─────────────────────────────────────────────────────
        critique = _self_critique(
            selected_tasks_for_critique, prev_concerns, eligible_tasks, merged_slots
        )
        agent_log.append({
            "step": f"Self-Critique — Iteration {iteration}",
            "content": critique,
        })

        if critique == "OK":
            logger.info("[Agent] Schedule approved after %d iteration(s).", iteration)
            break

    # ── Step 3: Build Schedule object from agent's final answer ───────────────
    schedule = Schedule(date=str(schedule_date), owner_id=owner.id)
    selected_ids: List[str] = []
    seen_ids: set = set()
    remaining = total_minutes

    for n in prev_selected_nums:
        task = task_index.get(n)
        if (
            task is not None
            and task.id not in seen_ids
            and task.duration_minutes <= remaining
        ):
            selected_ids.append(task.id)
            seen_ids.add(task.id)
            remaining -= task.duration_minutes

    schedule.selected_task_ids = selected_ids
    schedule.total_time = total_minutes - remaining
    schedule.explanation = (
        f"[AI] {prev_reasoning}"
        if prev_reasoning
        else "[AI] Schedule generated by agentic loop."
    )

    selected_titles = [
        t.title for t in eligible_tasks if t.id in seen_ids
    ]
    logger.info(
        "[Agent] Final: %d task(s) — %s | %d/%d min used",
        len(selected_ids),
        ", ".join(selected_titles) or "none",
        schedule.total_time,
        total_minutes,
    )
    agent_log.append({
        "step": "Final Schedule",
        "content": (
            f"Tasks selected ({len(selected_ids)}): "
            + (", ".join(selected_titles) or "none")
            + f"\nTime used: {schedule.total_time}/{total_minutes} min"
        ),
    })

    return schedule, agent_log
