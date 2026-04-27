import logging
import os

import streamlit as st
from datetime import time, date
from pawpal_system import Owner, Pet, Task, Schedule, TimeSlot

try:
    from ai_scheduler import run_agentic_schedule
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False


def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _from_minutes(m: int) -> time:
    return time(m // 60, m % 60)


def merge_slots(slots: list[TimeSlot]) -> list[TimeSlot]:
    """Merge overlapping or adjacent TimeSlots and return sorted, non-overlapping list."""
    if not slots:
        return []
    # Convert to (start_min, end_min) intervals, sort by start
    intervals = sorted(
        [(_to_minutes(s.start_time), _to_minutes(s.start_time) + s.duration_minutes) for s in slots]
    )
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:          # overlapping or adjacent — extend
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return [TimeSlot(start_time=_from_minutes(s), duration_minutes=e - s) for s, e in merged]


def task_emoji(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["walk", "run", "exercise"]): return "🚶"
    if any(k in t for k in ["feed", "food", "meal", "eat"]): return "🍽️"
    if any(k in t for k in ["med", "medicine", "pill", "vaccine"]): return "💊"
    if any(k in t for k in ["groom", "brush", "bath", "trim", "nail"]): return "✂️"
    if any(k in t for k in ["play", "toy", "fetch", "game"]): return "🎾"
    return "📋"


def species_emoji(species: str) -> str:
    s = species.lower()
    if s == "dog": return "🐕"
    if s == "cat": return "🐈"
    return "🐾"


# ─────────────────────────────────────────────
st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")
st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to the PawPal+ starter app.

This file is intentionally thin. It gives you a working Streamlit app so you can start quickly,
but **it does not implement the project logic**. Your job is to design the system and build it.

Use this app as your interactive demo once your backend classes/functions exist.
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.

You will design and implement the scheduling logic and connect it to this Streamlit UI.
"""
    )

with st.expander("What you need to build", expanded=True):
    st.markdown(
        """
At minimum, your system should:
- Represent pet care tasks (what needs to happen, how long it takes, priority)
- Represent the pet and the owner (basic info and preferences)
- Build a plan/schedule for a day that chooses and orders tasks based on constraints
- Explain the plan (why each task was chosen and when it happens)
"""
    )

st.divider()

# ── Owner setup ──────────────────────────────
st.subheader("Owner Info")
owner_name = st.text_input("Owner name", value="Jordan")

if st.button("Save owner"):
    if "owner" not in st.session_state:
        st.session_state.owner = Owner(name=owner_name)
    else:
        st.session_state.owner.name = owner_name
    st.success(f"Owner '{owner_name}' saved.")

# ── Owner preferences ─────────────────────────
st.subheader("Owner Preferences")
st.caption(
    "Preferred tasks and pets are boosted during scheduling. "
    "Enter comma-separated keywords that appear in task titles."
)

if "owner" not in st.session_state:
    st.info("Save owner info first.")
else:
    owner = st.session_state.owner

    col_pt, col_pp = st.columns(2)
    with col_pt:
        pref_tasks_input = st.text_input(
            "Preferred task keywords",
            value=", ".join(owner.preferences.get("preferred_tasks", [])),
            placeholder="e.g. walk, meds, feed",
        )
    with col_pp:
        pref_pets_input = st.text_input(
            "Preferred pet keywords",
            value=", ".join(owner.preferences.get("preferred_pets", [])),
            placeholder="e.g. Mochi, Whiskers",
        )

    if st.button("Save preferences"):
        owner.update_preferences(
            {
                "preferred_tasks": [k.strip() for k in pref_tasks_input.split(",") if k.strip()],
                "preferred_pets":  [k.strip() for k in pref_pets_input.split(",")  if k.strip()],
            }
        )
        st.success("Preferences saved.")

    prefs = owner.preferences
    if prefs["preferred_tasks"] or prefs["preferred_pets"]:
        st.table(
            [
                {"Type": "Preferred tasks", "Keywords": ", ".join(prefs["preferred_tasks"]) or "—"},
                {"Type": "Preferred pets",  "Keywords": ", ".join(prefs["preferred_pets"])  or "—"},
            ]
        )

# ── Available time slots ─────────────────────
st.subheader("Available Time Slots")
st.caption("Add one or more windows when you're free. Overlapping windows are merged automatically.")

if "owner" not in st.session_state:
    st.info("Save owner info first.")
else:
    if "raw_slots" not in st.session_state:
        st.session_state.raw_slots = []

    # Show raw slots + merged preview
    if st.session_state.raw_slots:
        st.write("Added slots:")
        st.table(
            [
                {
                    "From": s.start_time.strftime("%H:%M"),
                    "Duration (min)": s.duration_minutes,
                    "To": _from_minutes(
                        _to_minutes(s.start_time) + s.duration_minutes
                    ).strftime("%H:%M"),
                }
                for s in st.session_state.raw_slots
            ]
        )
        merged = merge_slots(st.session_state.raw_slots)
        if len(merged) < len(st.session_state.raw_slots):
            st.info(
                "Merged result: "
                + ", ".join(
                    f"{s.start_time.strftime('%H:%M')}–"
                    f"{_from_minutes(_to_minutes(s.start_time) + s.duration_minutes).strftime('%H:%M')}"
                    f" ({s.duration_minutes} min)"
                    for s in merged
                )
            )
    else:
        st.info("No time slots yet. Add one below.")

    with st.form("add_slot_form", clear_on_submit=True):
        col_s, col_d = st.columns(2)
        with col_s:
            new_slot_start = st.time_input("Available from", value=time(9, 0))
        with col_d:
            new_slot_dur = st.number_input("Duration (min)", min_value=5, max_value=480, value=60)
        if st.form_submit_button("Add time slot"):
            st.session_state.raw_slots.append(
                TimeSlot(start_time=new_slot_start, duration_minutes=int(new_slot_dur))
            )
            st.rerun()

    if st.session_state.raw_slots and st.button("Clear all slots"):
        st.session_state.raw_slots = []
        st.rerun()

# ── Pets ─────────────────────────────────────
st.divider()
st.subheader("Pets")

if "owner" not in st.session_state:
    st.info("Save owner info first.")
else:
    owner = st.session_state.owner
    pets = owner.get_pets()

    if pets:
        st.write("Current pets:")
        header = st.columns([3, 3, 1])
        header[0].markdown("**Name**")
        header[1].markdown("**Species**")
        for p in pets:
            col_n, col_s, col_r = st.columns([3, 3, 1])
            col_n.write(p.name)
            col_s.write(p.species)
            if col_r.button("Remove", key=f"remove_pet_{p.id}"):
                st.session_state.task_rows = [
                    r for r in st.session_state.task_rows if r.get("_pet_id") != p.id
                ]
                owner.remove_pet(p.id)
                st.session_state.pop("schedule", None)
                st.rerun()
    else:
        st.info("No pets yet. Add one below.")

    with st.form("add_pet_form", clear_on_submit=True):
        col_pn, col_sp = st.columns(2)
        with col_pn:
            new_pet_name = st.text_input("Pet name", value="Mochi")
        with col_sp:
            new_species = st.selectbox("Species", ["dog", "cat", "other"])
        if st.form_submit_button("Add pet"):
            owner.add_pet(Pet(name=new_pet_name, species=new_species))
            st.rerun()

# ── Tasks ─────────────────────────────────────
st.divider()
st.subheader("Tasks")
st.caption("Pick which pet the task belongs to, then add it.")

if "task_rows" not in st.session_state:
    st.session_state.task_rows = []

if "owner" not in st.session_state or not st.session_state.owner.get_pets():
    st.info("Add at least one pet before adding tasks.")
else:
    owner = st.session_state.owner
    pet_names = [p.name for p in owner.get_pets()]

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        task_title = st.text_input("Task title", value="Morning walk")
    with col2:
        duration = st.number_input("Duration (min)", min_value=1, max_value=240, value=20)
    with col3:
        priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)
    with col4:
        task_start = st.time_input("Start time", value=time(9, 0))
    with col5:
        selected_pet_name = st.selectbox("For pet", pet_names)

    col6, col7 = st.columns(2)
    with col6:
        task_due = st.date_input("Due date", value=date.today())
    with col7:
        freq_label = st.selectbox("Frequency", ["one-time", "daily", "weekly"])

    if st.button("Add task"):
        frequency = None if freq_label == "one-time" else freq_label
        target_pet = next(p for p in owner.get_pets() if p.name == selected_pet_name)
        task = Task(
            title=task_title,
            duration_minutes=int(duration),
            priority=priority,
            start_time=task_start,
            due_date=task_due,
            frequency=frequency,
        )
        target_pet.add_task(task)
        st.session_state.task_rows.append(
            {
                "_pet_id": target_pet.id,
                "_task_id": task.id,
                "Pet": selected_pet_name,
                "Title": task_title,
                "Duration (min)": int(duration),
                "Priority": priority,
                "Start Time": task_start.strftime("%H:%M"),
                "Due Date": task_due.strftime("%Y-%m-%d"),
                "Frequency": freq_label,
            }
        )
        st.rerun()

    if st.session_state.task_rows:
        PRIORITY_EMOJI = {"high": "🔴 High", "medium": "🟡 Medium", "low": "🟢 Low"}
        _pri_rank = {"high": 0, "medium": 1, "low": 2}
        sorted_rows = sorted(
            st.session_state.task_rows,
            key=lambda r: (_pri_rank.get(r["Priority"], 3), r["Duration (min)"])
        )
        pet_species = {p.name: p.species for p in owner.get_pets()}
        st.write("Current tasks:")
        header = st.columns([2, 3, 2, 2, 2, 2, 2, 2])
        for col, label in zip(header, ["Pet", "Title", "Duration (min)", "Priority", "Start Time", "Due Date", "Frequency", ""]):
            col.markdown(f"**{label}**")
        for row in sorted_rows:
            col_pet, col_title, col_dur, col_pri, col_st, col_due, col_freq, col_rm = st.columns([2, 3, 2, 2, 2, 2, 2, 2])
            col_pet.write(f"{species_emoji(pet_species.get(row['Pet'], 'other'))} {row['Pet']}")
            col_title.write(f"{task_emoji(row['Title'])} {row['Title']}")
            col_dur.write(row["Duration (min)"])
            col_pri.write(PRIORITY_EMOJI.get(row["Priority"], row["Priority"]))
            col_st.write(row["Start Time"])
            col_due.write(row.get("Due Date", "—"))
            col_freq.write(row.get("Frequency", "one-time"))
            if col_rm.button("Remove", key=f"remove_task_{row['_task_id']}"):
                pet_obj = next((p for p in owner.get_pets() if p.id == row["_pet_id"]), None)
                if pet_obj:
                    pet_obj.remove_task(row["_task_id"])
                st.session_state.task_rows = [
                    r for r in st.session_state.task_rows if r["_task_id"] != row["_task_id"]
                ]
                st.session_state.pop("schedule", None)
                st.rerun()
    else:
        st.info("No tasks yet. Add one above.")

# ── AI Scheduling Settings ────────────────────────────────────────────────
st.divider()
st.subheader("AI Scheduling Settings")

with st.expander("Configure AI scheduler (optional)", expanded=False):
    st.caption(
        "Provide an Anthropic API key to enable AI scheduling. "
        "The agent retrieves relevant pet-care guidelines (RAG) and self-critiques "
        "its plan before finalising the schedule."
    )
    api_key_default = os.environ.get("ANTHROPIC_API_KEY", "")
    api_key_input = st.text_input(
        "Google AI Studio API key",
        value=api_key_default,
        type="password",
        placeholder="AIza…",
        help="Get a free key at aistudio.google.com. Or set ANTHROPIC_API_KEY env var.",
    )
    if api_key_input:
        st.session_state["_api_key"] = api_key_input

    if not _AI_AVAILABLE:
        st.warning(
            "`anthropic` package not found. Run `pip install anthropic` to enable AI mode."
        )
    elif st.session_state.get("_api_key"):
        use_ai = st.checkbox(
            "Use AI scheduler",
            value=st.session_state.get("_use_ai", False),
            help="AI will plan, critique, and refine the schedule using RAG context.",
        )
        st.session_state["_use_ai"] = use_ai
        if use_ai:
            st.info(
                "AI mode ON — AI retrieves care guidelines and self-critiques "
                "the schedule before finalising it."
            )
    else:
        st.info("Enter an API key above to enable AI scheduling.")
        st.session_state["_use_ai"] = False

# ── Generate schedule ─────────────────────────
st.divider()
st.subheader("Build Schedule")
st.caption("Only tasks due on the selected date (one-time), or recurring on that date (daily / same weekday for weekly), will be considered.")
schedule_date = st.date_input("Schedule date", value=date.today())

if st.button("Generate schedule"):
    if "owner" not in st.session_state:
        st.warning("Please save owner info first.")
    elif not st.session_state.owner.get_pets():
        st.warning("Please add at least one pet first.")
    elif not any(p.tasks for p in st.session_state.owner.get_pets()):
        st.warning("Please add at least one task first.")
    elif not any(task.occurs_on(schedule_date) for p in st.session_state.owner.get_pets() for task in p.tasks):
        st.session_state.pop("schedule", None)
        st.warning(f"No tasks are scheduled for {schedule_date.strftime('%A, %Y-%m-%d')}.")
    elif not st.session_state.get("raw_slots"):
        st.warning("Please add at least one available time slot first.")
    else:
        owner = st.session_state.owner
        merged_slots = merge_slots(st.session_state.raw_slots)
        eligible_tasks = [
            task for p in owner.get_pets() for task in p.tasks
            if task.occurs_on(schedule_date)
        ]

        use_ai = st.session_state.get("_use_ai", False)
        api_key = st.session_state.get("_api_key", "").strip()

        if use_ai and _AI_AVAILABLE and api_key:
            with st.spinner("AI agent is building your schedule…"):
                try:
                    schedule, agent_log = run_agentic_schedule(
                        owner=owner,
                        eligible_tasks=eligible_tasks,
                        merged_slots=merged_slots,
                        schedule_date=schedule_date,
                        api_key=api_key,
                    )
                    st.session_state.agent_log = agent_log
                except Exception as exc:
                    logging.exception("AI scheduler failed")
                    st.error(f"AI scheduler error: {exc}. Falling back to rule-based mode.")
                    schedule = Schedule(date=str(schedule_date), owner_id=owner.id)
                    schedule.generate(
                        available_tasks=eligible_tasks,
                        available_slots=merged_slots,
                        owner_preferences=owner.preferences,
                    )
                    st.session_state.agent_log = []
        else:
            schedule = Schedule(date=str(schedule_date), owner_id=owner.id)
            schedule.generate(
                available_tasks=eligible_tasks,
                available_slots=merged_slots,
                owner_preferences=owner.preferences,
            )
            st.session_state.agent_log = []

        owner.add_schedule(schedule)
        st.session_state.schedule = schedule
        st.session_state.merged_slots = merged_slots

if "schedule" in st.session_state:
    s = st.session_state.schedule
    owner = st.session_state.owner
    pets = owner.get_pets()
    merged_slots = st.session_state.get("merged_slots", [])

    schedule_date_obj = date.fromisoformat(s.date) if s.date != "today" else date.today()  # also used in conflict check below
    st.success(f"Schedule for {schedule_date_obj.strftime('%A, %Y-%m-%d')} — {len(s.selected_task_ids)} task(s), {s.total_time} min total")
    st.markdown(f"**Explanation:** {s.explanation}")

    # Metric cards
    total_available = sum(slot.duration_minutes for slot in merged_slots)
    high_count = sum(1 for t in s.get_all_tasks(pets) if t.priority == "high")
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Tasks Scheduled", len(s.selected_task_ids))
    col_m2.metric("Total Time", f"{s.total_time} min")
    col_m3.metric("High Priority", high_count)

    # Progress bar
    if total_available > 0:
        st.progress(
            min(s.total_time / total_available, 1.0),
            text=f"Time used: {s.total_time} / {total_available} min ({round(s.total_time / total_available * 100)}%)"
        )

    # Pet lookup for the table
    pet_of = {task.id: pet for pet in pets for task in pet.tasks}

    # --- Sorted task table ---
    PRIORITY_EMOJI = {"high": "🔴 High", "medium": "🟡 Medium", "low": "🟢 Low"}

    st.markdown("#### Tasks (sorted by priority, then shortest → longest)")
    s.sort_by_time(pets)
    sorted_tasks = s.get_all_tasks(pets)

    if sorted_tasks:
        header = st.columns([2, 3, 2, 2, 2, 2, 1])
        for col, label in zip(header, ["Pet", "Title", "Priority", "Duration (min)", "Start Time", "Status", "Done"]):
            col.markdown(f"**{label}**")
        for t in sorted_tasks:
            col_pet, col_title, col_pri, col_dur, col_st, col_status, col_done = st.columns([2, 3, 2, 2, 2, 2, 1])
            pet_obj = pet_of.get(t.id)
            col_pet.write(f"{species_emoji(pet_obj.species) if pet_obj else '🐾'} {pet_obj.name if pet_obj else '—'}")
            col_title.write(f"{task_emoji(t.title)} {t.title}")
            col_pri.write(PRIORITY_EMOJI.get(t.priority, t.priority))
            col_status.write("✅ Done" if t.completed else "⏳ Pending")
            col_dur.write(t.duration_minutes)
            col_st.write(t.start_time.strftime("%H:%M") if t.start_time else "—")
            checked = col_done.checkbox(
                "Done", value=t.completed, key=f"sched_done_{t.id}",
                label_visibility="collapsed"
            )
            if checked and not t.completed:
                pet_obj = pet_of.get(t.id)
                if pet_obj:
                    pet_obj.complete_task(t.id)
                    # Sync any new recurring task into task_rows
                    new_tasks = [tk for tk in pet_obj.tasks if tk.id not in {r["_task_id"] for r in st.session_state.task_rows}]
                    for nt in new_tasks:
                        st.session_state.task_rows.append({
                            "_pet_id": pet_obj.id,
                            "_task_id": nt.id,
                            "Pet": pet_obj.name,
                            "Title": nt.title,
                            "Duration (min)": nt.duration_minutes,
                            "Priority": nt.priority,
                            "Start Time": nt.start_time.strftime("%H:%M") if nt.start_time else "—",
                            "Due Date": nt.due_date.strftime("%Y-%m-%d") if nt.due_date else "—",
                            "Frequency": nt.frequency if nt.frequency else "one-time",
                        })
                st.rerun()
    else:
        st.info("No tasks fit within the available time.")

    # --- Conflict detection ---
    st.markdown("#### Conflict Check")
    if merged_slots:
        # Conflicts among selected tasks (overlaps + overruns)
        warnings = s.detect_conflicts(pets, available_slots=merged_slots)
        selected_warnings = [] if warnings == ["No conflicts detected."] else warnings

        # Unselected tasks that conflict with a selected timed task
        # Only consider tasks eligible for this schedule's date to avoid false positives
        selected_id_set = set(s.selected_task_ids)
        all_tasks = [task for pet in pets for task in pet.tasks]
        unselected_timed = [
            t for t in all_tasks
            if t.id not in selected_id_set
            and t.start_time is not None
            and t.occurs_on(schedule_date_obj)
        ]
        selected_timed = [t for t in s.get_all_tasks(pets) if t.start_time is not None]

        def overlaps(a, b):
            a_start = a.start_time.hour * 60 + a.start_time.minute
            b_start = b.start_time.hour * 60 + b.start_time.minute
            return a_start < b_start + b.duration_minutes and b_start < a_start + a.duration_minutes

        conflict_rows = []
        for u in unselected_timed:
            for sel in selected_timed:
                if overlaps(u, sel):
                    conflict_rows.append(
                        {
                            "Skipped task": u.title,
                            "Priority": u.priority,
                            "Time": (
                                f"{u.start_time.strftime('%H:%M')}–"
                                f"{_from_minutes(_to_minutes(u.start_time) + u.duration_minutes).strftime('%H:%M')}"
                            ),
                            "Conflicts with": sel.title,
                            "Scheduled time": (
                                f"{sel.start_time.strftime('%H:%M')}–"
                                f"{_from_minutes(_to_minutes(sel.start_time) + sel.duration_minutes).strftime('%H:%M')}"
                            ),
                        }
                    )
                    break  # one match is enough per unselected task

        # Summary banner
        if not selected_warnings and not conflict_rows:
            st.success("No conflicts detected.")
        else:
            total = len(selected_warnings) + len(conflict_rows)
            st.warning(
                f"{total} conflict(s) detected: "
                f"{len(selected_warnings)} among scheduled tasks, "
                f"{len(conflict_rows)} skipped task(s) due to time conflicts."
            )

        for w in selected_warnings:
            st.warning(w)

        if conflict_rows:
            st.markdown("**Skipped tasks with time conflicts:**")
            st.table(conflict_rows)

    # --- AI Agent Log ---
    if st.session_state.get("agent_log"):
        st.markdown("#### AI Agent Log")
        st.caption(
            "Each step taken by the agentic scheduler: RAG retrieval, "
            "AI iterations, self-critiques, and final selection."
        )
        for entry in st.session_state.agent_log:
            with st.expander(entry["step"], expanded=False):
                st.text(entry["content"])
