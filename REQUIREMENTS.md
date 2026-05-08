# Requirements

## Project Overview

A CLI bedtime story generator that takes a free-text request from a user and produces a high-quality, age-appropriate story for children ages 5–10. The system uses a multi-agent pipeline — Classifier → PromptRouter → Storyteller → Judge → Refinement Loop — built on top of the existing `call_model()` skeleton using `gpt-3.5-turbo`.

---

## Functional Requirements

### FR-1: User Input
- The system MUST prompt the user for a free-text story request via the CLI.
- The system MUST validate the input:
  - Empty or whitespace-only input → re-prompt with a friendly message.
  - Input longer than 500 characters → trim to 500 and warn the user.
- The system MUST support a `--surprise` flag that generates a random story without user input.
- The system MUST support a `--age N` flag (5-10) for age-adaptive vocabulary.

### FR-2: Mood Detection
- The system MUST detect the child's emotional mood from the story request.
- Valid moods: calm, anxious, excited, sad, neutral.
- If mood is anxious, sad, or excited, the system MUST adjust the story tone accordingly.
- The detected mood MUST be displayed to the user.
- On detection failure, the system MUST default to "neutral" (no adjustment).

### FR-2: Story Classification
- The system MUST classify the user's request into exactly one of five categories:
  `adventure`, `friendship`, `fantasy`, `animals`, `bedtime`
- The system MUST use self-consistency (3 independent calls, majority vote) for reliable classification.
- If all votes are invalid, the system MUST default to `adventure`.
- The classified category MUST be displayed to the user before story generation begins.

### FR-3: Technique Selection
- The system MUST auto-select a prompting technique via the PromptRouter agent.
- The system MUST display the auto-selected technique to the user.
- The system MUST allow the user to override the technique selection with one of:
  - `standard` — chain-of-thought generation (1 API call)
  - `decompose` — least-to-most decomposition (2 API calls)
  - `self_correct` — generate + self-review + rewrite (2 API calls)
- If the user presses Enter without selecting, the system MUST use the auto-selected technique.
- The default fallback (on router failure) MUST be `decompose`.

### FR-4: Story Generation
- The system MUST generate a story using a category-specific system prompt tailored to the classified category.
- Stories MUST be appropriate for children ages 5–10:
  - Simple, age-appropriate vocabulary (no words > 3 syllables unless common).
  - Clear story arc: introduction → problem → journey → resolution → peaceful ending.
  - Positive moral or life lesson woven naturally.
  - No violence, weapons, death, or scary content.
  - Approximate length: 300–400 words.
- All generation paths MUST include chain-of-thought planning and negative constraints.
- On a refinement pass, the system MUST incorporate structured feedback from the Judge.

### FR-5: Story Evaluation (Judge)
- The system MUST evaluate every generated story on four dimensions, each scored 1–5:
  - `vocabulary_score` — simplicity and age-appropriateness of language.
  - `engagement_score` — imaginative quality and child appeal.
  - `story_arc_score` — presence of a clear beginning, middle, and end.
  - `moral_score` — presence of a positive lesson.
- The Judge MUST use a scoring rubric with explicit definitions for scores 1, 3, and 5.
- The Judge MUST include one few-shot calibration example for consistent scoring.
- The Judge MUST return an `overall` score (average of the four), `feedback` text, and a `specific_fixes` list.
- The system MUST recompute `overall` from the four scores (do not trust model arithmetic).
- The Judge response MUST be valid JSON. The system MUST handle malformed JSON gracefully:
  1. Try direct `json.loads()`
  2. Regex extraction of first `{...}` block
  3. Retry the API call once
  4. Fall back to DEFAULT_RESULT (all 5s, empty fixes)

### FR-6: Refinement Loop
- The system MUST run a maximum of 2 generation attempts.
- If the Judge's `overall` score is >= 4.0, the loop exits early and the story is accepted.
- If the score is < 4.0 and iterations remain, the system MUST pass the Judge's feedback back to the Storyteller for a refined attempt (feedback injection technique).
- The system MUST track the best-scoring story across all iterations and present that one to the user.

### FR-7: Score Display
- After each Judge evaluation, the system MUST print a formatted score table showing:
  - Individual scores as a filled/empty block bar (e.g., `████░  4/5`).
  - Overall score with a PASS (>= 4.0) or NEEDS WORK (< 4.0) indicator.

### FR-8: Story Display
- The system MUST display the final story with a clear header and separator.
- The system MUST display an estimated reading time based on word count (130 WPM for children ages 5–10).

### FR-9: User Feedback (Post-Story)
- After displaying the final story, the system MUST offer three options:
  - [1] Request changes (feedback injection)
  - [2] Continue the story (sequel with same characters)
  - [Enter] Finish and exit
- If the user provides feedback, the system MUST generate and display a revised story.
- User feedback MUST be trimmed to 200 characters if longer.

### FR-10: Story Title
- After story generation, the system MUST generate a creative title (3-7 words).
- The title MUST be displayed above the story text.
- On failure, the system MUST fall back to "A Bedtime Story".

### FR-11: Moral Extraction
- After story generation, the system MUST extract the moral/lesson in one sentence.
- The moral MUST be displayed below the story as: `Lesson: "..."`.
- On failure, the system MUST fall back to a generic message.

### FR-12: Story Continuation
- After displaying the story, the system MUST offer a "what happens next?" option.
- If selected, the system MUST generate a 200-300 word sequel using the same characters.
- The continuation MUST maintain character consistency via CharacterMemory.
- The continuation MUST also receive a title and moral.

### FR-13: Age-Adaptive Vocabulary
- The system MUST support a `--age N` flag (5-10) to adjust vocabulary complexity.
- Age 5: only 1-2 syllable words, sentences under 8 words, ~250 word stories.
- Age 10: varied vocabulary, complex sentences OK, 350-450 word stories.
- Default age: 7 (if flag not provided).

### FR-14: Character Memory
- The system MUST extract and store character descriptions after story generation.
- Stored characters MUST be used for story continuation.
- Character memory persists within a single session only.

### FR-15: Session Summary
- At the end of each session, the system MUST display:
  - Total API calls made
  - Estimated token usage (prompt + completion)
  - Estimated cost based on gpt-3.5-turbo pricing

### FR-11: API Key Handling
- The system MUST check for `OPENAI_API_KEY` at startup.
- If the key is missing or empty, the system MUST print a clear error message with instructions and exit with a non-zero code.
- The API key MUST NOT be hardcoded anywhere in the codebase.

### FR-12: Error Handling
- On `RateLimitError`: wait 5 seconds and retry once.
- On `APIError` or `Timeout`: print the error and exit.
- On empty API response: retry once, then raise `ValueError`.
- On PromptRouter failure: fall back to `decompose` silently (graceful degradation).
- On Judge JSON parse failure: regex fallback → retry → DEFAULT_RESULT.
- On any other unexpected exception: print the error and exit.

---

## Non-Functional Requirements

### NFR-1: Model
- MUST use `gpt-3.5-turbo` via the `call_model()` function. The model name MUST NOT be changed.

### NFR-2: Dependencies
- Only `openai` is required as an external dependency.
- Standard library modules only: `os`, `sys`, `json`, `re`, `time`, `random`, `collections`.

### NFR-3: Code Structure
- Code MUST be split across files: `main.py`, `agents.py`, `prompts.py`, `utils.py`.
- `prompts.py` MUST contain only string constants — no logic.
- `utils.py` MUST contain only stateless helper functions and the TokenTracker class.
- `agents.py` MUST contain only agent classes: `Classifier`, `PromptRouter`, `Storyteller`, `Judge`.

### NFR-4: Code Quality
- All functions MUST have type hints.
- All functions and classes MUST have docstrings explaining purpose, args, and returns.
- Code MUST include inline comments explaining non-obvious decisions.
- Code MUST be readable by another developer without external documentation.

### NFR-5: Testability
- The project MUST include a test suite (`tests.py`) with unit and integration tests.
- Tests MUST run without an API key (all API calls mocked).
- Tests MUST cover: input validation, JSON parsing, score display, environment check, classifier, router, judge, storyteller.

### NFR-6: Usability
- All progress steps MUST be communicated to the user via printed messages before API calls.
- The CLI MUST feel friendly and approachable.
- The user MUST be able to see which technique was selected and override it.

### NFR-7: Security
- `.env.example` MUST exist with only `OPENAI_API_KEY=` and nothing else.
- `.gitignore` MUST exclude `.env`, `__pycache__/`, and IDE files.
- No secrets MUST appear in any committed file.

### NFR-8: Robustness
- The pipeline MUST never crash due to:
  - Malformed LLM output (Judge JSON, Classifier response, Router response)
  - Empty API responses
  - PromptRouter failures
- Every failure path MUST have a graceful fallback.

---

## Constraints

| Constraint | Value |
|---|---|
| Model | `gpt-3.5-turbo` (fixed) |
| Max story tokens | 700 |
| Max judge tokens | 300 |
| Max classifier tokens | 20 per call (x3 for self-consistency) |
| Max router tokens | 20 |
| Max refinement iterations | 2 |
| Max user input length | 500 characters |
| Max user feedback length | 200 characters |
| Story target length | 300–400 words |
| Story age target | 5–10 years old |
| Acceptance threshold | overall >= 4.0 / 5.0 |
| Reading speed estimate | 130 WPM (children being read to) |

---

## Out of Scope

- Streaming output.
- Persistent storage or session history.
- Web or GUI interface.
- Multi-turn conversation beyond the single post-story feedback pass.
- Support for models other than `gpt-3.5-turbo`.
- Exact token counting (uses ~4 chars/token heuristic).
- Authentication or multi-user support.
