# Model Card — PawPal+ AI Scheduler

## Limitations and Biases

**Knowledge base scope.** The RAG retriever draws from 10 hand-written care guidelines. These were written with common household pets (dogs and cats) in mind. Exotic pets — reptiles, birds, rabbits — are not well represented. A query for a parrot's feeding schedule will retrieve the most statistically similar guideline, which may be loosely relevant at best and misleading at worst.

**TF-IDF is not semantic.** The retrieval layer matches on word overlap, not meaning. "Administer insulin" and "give meds" score differently even though they describe the same thing. 

**Scheduling assumes independence.** The model is not told whether two tasks conflict in time — it only knows start times and durations. If the owner enters two tasks at 09:00 and the model selects both, the system flags it as a concern but does not prevent it. The responsibility for resolving that falls on the next iteration (or the user).

**No personalization over time.** Each scheduling session starts fresh. The model has no memory of which tasks the owner typically skips, which pets need extra attention this week, or how last Tuesday's schedule actually played out.

---

## Potential Misuse and Mitigations

The most realistic misuse is **over-reliance on the AI output for medically sensitive tasks**. A user might trust the generated schedule for a pet on a strict medication regimen without verifying that the AI included it correctly.

Mitigations already in place:
- The self-critique loop enforces that HIGH-priority tasks are never silently dropped.
- The explanation field always begins with `[AI]` and includes the model's reasoning, so the user can read *why* a task was or wasn't selected rather than accepting it blindly.
- The rule-based fallback runs automatically if the API is unavailable, ensuring the app never silently produces an empty schedule.

What is not mitigated: a user who does not read the explanation and treats the output as ground truth. 
---

## What Surprised Me During Reliability Testing

**Identical task names across pets broke the title-matching entirely.** In the first version of AI generated code, when two pets both had a task called "Morning Walk," the scheduler always selected the first one found and blocked the second as a duplicate. Even I designed the ID in task class to avoid this issue. I switched from fuzzy title matching to numbered task IDs in the prompt and resolved the issue completely. 

---

## Collaboration with AI During This Project

AI assistance (Claude) was used throughout this project for code generation, debugging, and design review.

**Helpful instance — diagnosing the double-space bug.** When testing with pets whose task titles had double spaces (e.g., `"Morning  Feed"`), the self-critique was incorrectly flagging those tasks as unselected even after the model had chosen them. The AI correctly identified that Python's `in` operator treats `"morning  feed"` and `"morning feed"` as different strings and suggested normalizing both sides with `" ".join(s.lower().split())` before comparing. This was a non-obvious fix that would have taken significant manual debugging to find.

**Flawed instance — the initial agentic loop design.** Early in development, the AI suggested maintaining a running `messages` list manually and appending each turn to simulate multi-turn conversation. This worked but was redundant: the `google-genai` client's `chat` object already maintains conversation history internally. Following the original suggestion would have created a hidden state-management bug where the same messages were sent twice on each iteration, inflating token usage. Reviewing the SDK documentation revealed the correct approach: call `chat.send_message()` and let the client handle history automatically.
