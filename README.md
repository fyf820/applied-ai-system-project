# PawPal+ — AI-Powered Pet Care Scheduler

## Original Project (Modules 1–3)

PawPal+ began as a rule-based pet care planning assistant. The original system let a pet owner enter their pets, daily care tasks (walks, feeding, medication, grooming), and available time windows, then generated an optimized daily schedule using a greedy algorithm that ranked tasks by priority, owner preferences, and start time. It also detected scheduling conflicts and handled recurring tasks (daily and weekly).

The Module 1–3 implementation covered the full `Owner → Pet → Task → Schedule` class hierarchy, a Streamlit UI, and a pytest suite with 13 tests — but had **no AI or language model integration**.

---

## Title and Summary

**PawPal+ AI Extension** adds two advanced AI features on top of the original scheduler:

| Feature | What it does |
|---|---|
| **RAG (Retrieval-Augmented Generation)** | Before scheduling, the system retrieves the most relevant pet-care guidelines from a knowledge base and injects them into Claude's prompt. This means Claude's decisions are grounded in expert advice (e.g., "medications must never be skipped", "dogs need 60+ min of exercise daily") rather than just the task list. |
| **Agentic Scheduling Loop** | Claude drafts a schedule, then a rule-based self-critique checks it (missed any HIGH-priority tasks?). If issues are found, Claude revises — up to 3 rounds — before the final schedule is built. Every step is logged and visible in the UI. |

**Why it matters:** Pet owners often have more tasks than time. A scheduler that can reason about *why* certain tasks matter — not just sort by priority — gives more trustworthy, explainable results. The agentic loop means the system catches its own mistakes before presenting them to the user.

---

## Architecture Overview

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system diagram.

```
User Input (Streamlit)
    │
    ├──► RAG Retriever (pet_care_kb.py)
    │       Scores 10 care guidelines with TF-IDF + tag-match bonus
    │       Returns top-4 relevant docs  ──────────────────────┐
    │                                                           │
    └──► Agentic Scheduler (ai_scheduler.py)  ◄────────────────┘
            │
            ├── Iteration 1: Claude drafts SELECTED TASKS / REASONING / CONCERNS
            │
            ├── Self-Critique: rule-based check
            │       • Any HIGH-priority task skipped that could fit?
            │       • Unresolved concerns from the model?
            │
            ├── If issues found → Claude revises (up to 3 rounds)
            │
            └── Approved schedule → Schedule object → Streamlit display

Fallback: if no API key (or API error), the original greedy algorithm runs instead.
Test Suite (pytest, 13 tests) validates the core scheduling logic independently.
```
![alt text](../assets/pet_diagram.svg)

**Key files:**

| File | Role |
|---|---|
| `pawpal_system.py` | Core data classes: `Owner`, `Pet`, `Task`, `Schedule`, `TimeSlot` |
| `pet_care_kb.py` | RAG knowledge base (10 guidelines) + TF-IDF retriever |
| `ai_scheduler.py` | Agentic loop: RAG → Claude draft → self-critique → revise → build |
| `app.py` | Streamlit UI: input, AI settings, schedule display, agent log |
| `test/test_pawpal.py` | 13 pytest tests for scheduling, recurrence, and conflict detection |

---

## Setup Instructions

### 1. Clone / navigate to the project

```bash
cd applied-ai-system-project
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` includes:
```
streamlit>=1.30
pytest>=7.0
google-generativeai>=0.8.0
```

### 4. Set your Google AI Studio API key (for AI mode)

Get a free key at **aistudio.google.com → Get API key**.

```bash
# macOS / Linux
export ANTHROPIC_API_KEY="AIza..."

# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="AIza..."
```

Or paste it directly into the "Configure AI scheduler" expander inside the app — no environment variable needed.

> AI mode is optional. If no key is provided, the original rule-based scheduler runs automatically.

### 5. Run the app

```bash
streamlit run app.py
```

### 6. Run the tests

```bash
python -m pytest
```
Output:
![alt text](../assets/test.png)
---

## Sample Interactions

### Example 1 — Rule-Based Mode (no API key)

**Setup:**
- Owner: Jordan, available 09:00–10:00 (60 min)
- Pet: Mochi (dog)
- Tasks:
  - Give Mochi meds — 5 min, HIGH, 10:00
  - Morning walk — 30 min, MEDIUM, 09:00
  - Brush coat — 15 min, LOW, 09:30

**Output:**
```
Schedule for Sunday, 2026-04-26 — 3 task(s), 50 min total

Explanation: Tasks selected: Give Mochi meds (high priority),
             Morning walk (medium priority), Brush coat (low priority)

Tasks Scheduled: 3   |   Total Time: 50 min   |   High Priority: 1
Time used: 50 / 60 min (83%)
```

All three tasks fit, with the HIGH medication task selected first.

---

### Example 2 — AI Mode, RAG in action

**Setup:**
- Owner: Jordan, available 09:00–09:30 (30 min — tight!)
- Pet: Mochi (dog)
- Tasks:
  - Give Mochi meds — 10 min, HIGH, 09:00
  - Morning walk — 30 min, HIGH, 09:00  ← same priority, same time, won't both fit
  - Play fetch — 15 min, LOW, 09:10

**RAG — Retrieved Care Guidelines (logged in UI):**
```
• Medications must be given at consistent times and are always the HIGHEST priority
  on any schedule. Missing a dose can be medically serious.
• Dogs need 30–60 min of exercise daily; Morning walks should be treated as HIGH priority.
• If total task time exceeds available slots, drop LOW-priority tasks first, then MEDIUM.
  Never drop HIGH-priority tasks unless there is literally no time.
• Always schedule HIGH-priority tasks first. Never skip HIGH tasks if they fit.
```

**Agent — Iteration 1:**
```
SELECTED TASKS: Give Mochi meds, Play fetch
REASONING: According to the care guidelines, medications must always be the highest
priority and should never be skipped. With only 30 minutes available and both tasks
marked HIGH priority, I selected the medication (10 min) first. Play fetch (15 min)
fills the remaining time. The full 30-min walk exceeds the available slot.
CONCERNS: Morning walk (HIGH) was skipped due to insufficient time — owner should
schedule a separate slot for exercise today.
```

**Self-Critique — Iteration 1:**
```
Model flagged: Morning walk (HIGH) was skipped due to insufficient time —
owner should schedule a separate slot for exercise today.
```

**Agent — Iteration 2 (revised):**
```
SELECTED TASKS: Give Mochi meds, Morning walk
REASONING: Re-evaluating: both meds (10 min) and the morning walk (30 min) are HIGH
priority, but together they total 40 min which exceeds the 30-min slot. Per the
guidelines, medications take precedence. However, the walk fits if meds is done first
(10 min) leaving 20 min — not the full 30 min. I select meds + as much of the walk
as possible. Play fetch is LOW priority and is dropped.
CONCERNS: Walk duration (30 min) slightly exceeds remaining time (20 min).
Owner may need to shorten today's walk.
```

**Self-Critique — Iteration 2:**
```
OK
```

**Final schedule explanation shown in UI:**
```
[AI] Re-evaluating: both meds (10 min) and the morning walk (30 min) are HIGH priority...
     Medications take precedence. Play fetch is LOW priority and is dropped.
```

---

### Example 3 — Multiple pets, preferences applied

**Setup:**
- Owner: Sarah, available 09:00–10:30 (90 min), preferred pets: `["Mochi"]`
- Pet 1: Mochi (dog) — Walk 30 min HIGH, Meds 5 min HIGH
- Pet 2: Whiskers (cat) — Feed 10 min HIGH, Groom 20 min MEDIUM

**RAG retrieved:** guidelines on dog exercise, medication priority, cat feeding, multiple-pet scheduling

**Agent output:**
```
SELECTED TASKS: Give Mochi meds, Walk Mochi, Feed Whiskers, Groom Whiskers
REASONING: Per care guidelines, medications are the highest priority and were scheduled
first (5 min). Mochi's walk follows as HIGH priority and owner-preferred pet (30 min).
Whiskers' feeding is HIGH priority (10 min). Grooming fills remaining time as MEDIUM
priority (20 min). Total: 65 min of 90 available.
CONCERNS: None
```

Self-critique: `OK` on the first iteration — no revision needed.

---

Sample output in APP:
![alt text](../assets/AIoutput.png)

## Design Decisions

### Why RAG over a simple system prompt?

I could have hard-coded pet care rules directly into Claude's system prompt. Instead, I built a retrieval layer (`pet_care_kb.py`) that scores documents against the *specific* pets and tasks in the current session. This means the prompt only receives the 4 most relevant guidelines — not all 10 — keeping token usage low while ensuring the advice is contextually appropriate. It also makes the knowledge base easy to extend (just add entries to `KNOWLEDGE_BASE`).

**Trade-off:** TF-IDF without embeddings is less semantically precise than a vector database. For 10 documents this is fine; at hundreds of entries a proper embedding store (e.g., ChromaDB) would be needed.

### Why an agentic loop with rule-based critique rather than pure Claude?

Letting Claude self-evaluate purely in natural language risks it convincing itself that a bad schedule is fine. The rule-based self-critique is deterministic: it checks hard constraints (HIGH tasks that fit but were skipped) that shouldn't be open to interpretation. This hybrid approach — LLM for reasoning, rules for verification — is more reliable than either alone.

**Trade-off:** The loop adds latency (up to 3 API calls). The `MAX_ITERATIONS = 3` cap prevents runaway loops. `claude-haiku-4-5-20251001` was chosen over Sonnet to minimize cost per iteration.

### Why keep the rule-based scheduler as a fallback?

The original greedy scheduler is fast, deterministic, and fully tested. Keeping it means the app is useful without an API key and remains reliable if the API is unavailable. The AI mode enhances the scheduler rather than replacing it.

### Why move tasks from `Schedule` to `Pet`?

The original UML had `Schedule → Task`. During implementation it became clear that tasks (walk Mochi, give Whiskers her meds) belong to a specific pet, not to a schedule. The schedule just selects *which* of a pet's tasks to include on a given day. This restructuring made filtering, recurrence, and multi-pet support much cleaner.

---

## Testing Summary

```bash
python -m pytest -v       # runs all 26 tests across both test files
```

**26 / 26 tests passed.**

---

### File 1: `test/test_pawpal.py` — Core scheduling logic (13 tests)

| Test | What it verifies |
|---|---|
| `test_generate_respects_priority` | HIGH task selected over LOW when only one fits |
| `test_sort_by_time_orders_shortest_first` | Duration sort is ascending |
| `test_daily_recurring_task_creates_next_day_occurrence` | Completing a daily task enqueues due_date + 1 |
| `test_non_recurring_task_does_not_spawn_next_occurrence` | One-time tasks don't grow the list |
| `test_conflict_detected_for_same_start_time` | Overlap warning fired for two tasks at 09:00 |
| `test_conflict_detected_when_task_outside_available_slot` | Overrun warning fired for task outside owner's window |
| `test_pet_with_no_tasks_produces_empty_schedule` | Edge case: no crash, `total_time == 0` |
| `test_occurs_on_*` (3 tests) | One-time, daily, and weekly recurrence date logic |
| `test_add_task_increases_task_count` | Task count and `total_time` update correctly |
| `test_mark_complete_changes_status` | `completed` flag flips to True |

---

### File 2: `test/test_ai_components.py` — AI components (14 tests)

**Group 1 — RAG Retriever** (4 tests, deterministic, no API key needed)

| Test | What it verifies | Result |
|---|---|---|
| `test_medication_query_retrieves_medication_guideline` | Meds task → medication guideline appears in top-4 | ✅ Pass |
| `test_dog_walk_query_retrieves_exercise_guideline` | Dog + walk task → exercise guideline appears in top-4 | ✅ Pass |
| `test_retrieve_returns_exactly_top_k_results` | `top_k=3` returns exactly 3 docs | ✅ Pass |
| `test_retrieve_no_duplicate_documents` | No content string appears twice | ✅ Pass |

**Group 2 — Self-Critique** (4 tests)

| Test | What it verifies | Result |
|---|---|---|
| `test_critique_ok_when_all_high_tasks_are_included` | No complaint when HIGH tasks are all selected | ✅ Pass |
| `test_critique_flags_skipped_high_task_that_fits` | Flags a HIGH task that was skipped but could fit | ✅ Pass |
| `test_critique_ok_when_high_task_genuinely_cannot_fit` | No false alarm when HIGH task truly can't fit | ✅ Pass |
| `test_critique_surfaces_unresolved_model_concerns` | Claude's own concern is surfaced in the critique | ✅ Pass |

**Group 3 — Task Matching** (4 tests)

| Test | What it verifies | Result |
|---|---|---|
| `test_match_exact_title` | Exact title always matches | ✅ Pass |
| `test_match_returns_correct_task_among_multiple` | Right task selected from a list of two | ✅ Pass |
| `test_match_word_overlap_handles_paraphrasing` | "Mochi meds" still finds "Give Mochi meds" | ✅ Pass |
| `test_match_unrelated_title_returns_none` | Hallucinated title returns `None`, not wrong task | ✅ Pass |

**Group 4 — Confidence Scoring** (2 tests)

| Test | What it verifies | Result |
|---|---|---|
| `test_confidence_is_1_when_schedule_is_perfect` | All HIGH tasks + full time = score 1.0 | ✅ Pass |
| `test_confidence_below_0_6_when_high_task_skipped` | Skipped HIGH task pulls score below 0.6 | ✅ Pass |

---

### Confidence scoring

`compute_confidence()` in `ai_scheduler.py` scores each generated schedule on a 0–1 scale:

```
score = 0.6 × (HIGH tasks included / total HIGH tasks)
      + 0.4 × (time used / total available minutes)
```

| Scenario | Score | Interpretation |
|---|---|---|
| All HIGH tasks, 83% time used | **0.93** | Excellent |
| All HIGH tasks, 50% time used | **0.80** | Good — consider adding low-priority tasks |
| One HIGH task skipped, 100% time used | **0.40** | Poor — critical task was missed |
| No HIGH tasks defined, 70% time used | **0.88** | Good — nothing critical to miss |

The score is logged to `pawpal.log` and shown as the last entry in the AI Agent Log in the UI.

---

### What the tests proved and what they didn't

**What worked:**
- The RAG retriever consistently surfaces contextually relevant guidelines (medication rules for med tasks, exercise rules for dog walk tasks).
- The self-critique correctly catches skipped HIGH tasks and surfaces unresolved model concerns, without producing false alarms for tasks that genuinely can't fit.
- Task matching is robust to common LLM paraphrasing (shortened titles, different word order).

**Known limitation:**
When a one-time task and a weekly task share the same priority and time window, the rule-based scheduler applies FIFO ordering (first-added wins). The AI scheduler handles this through Claude's reasoning, but no automated test covers it yet.

**Testing summary:**
Passed all 26/26 unit tests. Human evaluated incorrect generated schedules, but accuracy improved after adding validation rules.
---

## Reflection

See [model_card.md](model_card.md) for the full reflection.

### What this project taught about AI

**Grounding matters more than capability.** Claude is capable of reasoning about pet care on its own, but without the RAG context it sometimes makes generic decisions that ignore specific constraints (e.g., suggesting a 60-min walk when only 20 min is available). Injecting retrieved knowledge forces the model to reason from evidence, which produces more consistent and trustworthy outputs.

**Hybrid systems outperform pure LLMs for rule-critical tasks.** The self-critique loop taught me that LLMs are excellent at language and nuanced reasoning, but they can "reason themselves" into ignoring hard constraints. A rule-based checker that says "HIGH task X was skipped and 20 min remain — fix this" is more reliable than asking Claude to notice the same thing on its own.

**Prompting format is architecture.** The structured reply format (`SELECTED TASKS / REASONING / CONCERNS`) made parsing reliable and forced Claude to be explicit about its decisions. Unstructured responses would have made the agentic loop fragile.

**Fallbacks prevent fragility.** Building the AI as an *enhancement* rather than a *replacement* meant the app remained functional throughout development and API testing. A system that degrades gracefully under failure is more useful than one that's powerful but brittle.

### What I would improve next

- Add embeddings-based retrieval (ChromaDB) to scale the knowledge base beyond ~20 entries.
- Mock the Anthropic API in pytest to test the full agentic loop end-to-end without hitting the network, catching response-parsing failures before they reach users.
