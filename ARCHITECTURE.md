# PawPal+ System Architecture

## Component Overview

| Component | File | Role |
|---|---|---|
| **Streamlit UI** | `app.py` | Collects owner/pet/task input; renders output |
| **RAG Retriever** | `pet_care_kb.py` | Fetches relevant care guidelines before scheduling |
| **Agentic Scheduler** | `ai_scheduler.py` | Claude drafts, self-critiques, and refines the schedule |
| **Rule-Based Scheduler** | `pawpal_system.py` | Greedy fallback when no API key is provided |
| **Test Suite** | `test/test_pawpal.py` | 13 pytest tests validating core logic |

---

## System Diagram

```mermaid
flowchart TD

    %% ── Human ──────────────────────────────────────────────────────────────
    USER(["👤 Owner / Human"])

    %% ── Input ──────────────────────────────────────────────────────────────
    subgraph UI["🖥️  Streamlit UI  ·  app.py"]
        direction TB
        IN_DATA["User Input\nOwner name · Pets · Tasks\nTime slots · API key"]
    end

    %% ── RAG ────────────────────────────────────────────────────────────────
    subgraph RAG["📚  RAG Retriever  ·  pet_care_kb.py"]
        direction TB
        KB[("Knowledge Base\n10 expert care guidelines\n(exercise · feeding · meds\ngrooming · play · scheduling)")]
        TFIDF["TF-IDF Scorer\n+ tag-match bonus\nreturns top-4 docs"]
        KB --> TFIDF
    end

    %% ── Agentic loop ────────────────────────────────────────────────────────
    subgraph AGENT["🤖  Agentic Scheduler  ·  ai_scheduler.py"]
        direction TB
        CLAUDE["Gemini 2.0 Flash\n― selects tasks\n― writes reasoning\n― flags concerns"]
        CRITIC["Self-Critique\nRule-based checker\n• Any HIGH task skipped that fits?\n• Unresolved model concerns?"]
        CLAUDE -->|"SELECTED TASKS\nREASONING · CONCERNS"| CRITIC
        CRITIC -->|"issues found\n↺ revise  (≤ 3 rounds)"| CLAUDE
    end

    %% ── Fallback ────────────────────────────────────────────────────────────
    subgraph FALLBACK["⚙️  Rule-Based Fallback  ·  pawpal_system.py"]
        GREEDY["Greedy Algorithm\npriority → preference → start-time\n(used when no API key or on error)"]
    end

    %% ── Output ──────────────────────────────────────────────────────────────
    subgraph OUTPUT["📊  Schedule Output  ·  Streamlit UI"]
        direction TB
        SCHED["Schedule Object\nselected task IDs · total time · explanation"]
        DISPLAY["Task Table + Metrics\nprogress bar · mark-done checkboxes"]
        CONFLICTS["Conflict Detector\noverlapping tasks · slot overruns"]
        ALOG["AI Agent Log\nRAG docs retrieved\nper-iteration replies\nself-critique results"]
        SCHED --> DISPLAY & CONFLICTS & ALOG
    end

    %% ── Testing ─────────────────────────────────────────────────────────────
    subgraph TESTING["🧪  Test Suite  ·  test/test_pawpal.py"]
        PYTEST["pytest  (13 tests)\n• Priority scheduling\n• Recurrence logic\n• Conflict detection\n• Edge cases"]
    end

    %% ── Data-flow edges ─────────────────────────────────────────────────────

    USER -->|"enters owner, pets,\ntasks, time slots"| IN_DATA

    IN_DATA -->|"task titles + pet species\nbuild retrieval query"| TFIDF
    TFIDF  -->|"top-4 care guidelines\ninjected into prompt"| CLAUDE
    IN_DATA -->|"full scheduling context\n+ API key"| CLAUDE

    IN_DATA -->|"no API key provided\nor API error"| GREEDY

    CRITIC  -->|"✅ approved"| SCHED
    GREEDY  --> SCHED

    DISPLAY & CONFLICTS & ALOG -->|"human reviews schedule\nmarks tasks complete"| USER

    PYTEST -.->|"validates scheduling logic"| GREEDY
    PYTEST -.->|"validates Schedule methods"| SCHED
```

---

## Data Flow  (step-by-step)

```
Input
  └─ Human fills in: owner info, pets, tasks (title/priority/duration/time), available slots

      │
      ▼
RAG Retrieval  (pet_care_kb.py)
  └─ Query = task titles + pet species
  └─ TF-IDF scores all 10 guidelines → returns top-4 most relevant

      │  top-4 care guideline strings
      ▼
Agentic Draft  (ai_scheduler.py  ·  Iteration 1)
  └─ Prompt = RAG context + scheduling context
  └─ Claude replies: SELECTED TASKS / REASONING / CONCERNS

      │
      ▼
Self-Critique  (rule-based)
  ├─ All HIGH-priority tasks included that could fit?
  └─ Any unresolved concerns flagged by the model?

      ├── ✅ "OK"  →  accepted, exit loop
      └── ⚠️  issues  →  feed critique back to Claude (up to 3 rounds)

      │
      ▼
Schedule Object built from Claude's final answer
  └─ Fuzzy title matching maps names → Task IDs → Schedule.selected_task_ids

      │
      ▼
Output (Streamlit UI)
  ├─ Task table with priority / duration / status / mark-done
  ├─ Conflict detection (overlaps + slot overruns)
  └─ AI Agent Log (expandable: RAG docs, each iteration, each critique)

      │
      ▼
Human reviews → marks tasks done → recurring tasks auto-enqueue next occurrence
```

---

## Where Human Oversight & Testing Occur

| Point | Type | What happens |
|---|---|---|
| Task creation | **Human input** | Owner decides task priorities and durations |
| Schedule review | **Human review** | Owner inspects the generated schedule before acting |
| Mark complete | **Human action** | Owner confirms each task was actually done |
| Self-Critique | **Automated check** | Rules verify HIGH-priority coverage after each Claude iteration |
| `pytest` suite | **Automated testing** | 13 tests verify scheduling correctness, conflict detection, and recurrence logic |
| AI Agent Log | **Human auditability** | Every RAG doc and Claude iteration is visible in the UI |
