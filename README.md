# Bedtime Story Generator

### A Multi-Agent AI Pipeline for Children's Bedtime Stories

An intelligent CLI tool that generates high-quality, age-appropriate bedtime stories for children ages 5–10. Built with 8 specialized AI agents, 12 prompting techniques, mood-adaptive tone, and a closed-loop quality control system.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [System Architecture](#system-architecture)
- [Agents](#agents)
- [Prompting Techniques](#prompting-techniques)
- [Usage Examples](#usage-examples)
- [How Quality is Ensured](#how-quality-is-ensured)
- [Design Decisions](#design-decisions)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Example Output](#example-output)

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd AI\ Agent\ Deployment\ Engineer\ Takehome

# 2. Install the only dependency
pip install openai

# 3. Set your API key
export OPENAI_API_KEY=your_key_here

# 4. Run
python3 main.py
```

---

## Features

| Feature | Description |
|---|---|
| **8 AI Agents** | Classifier, MoodDetector, PromptRouter, Storyteller, Judge, TitleGenerator, MoralExtractor, CharacterMemory |
| **12 Prompting Techniques** | Self-consistency, chain-of-thought, least-to-most, self-correction, few-shot, feedback injection, and more |
| **Mood-Adaptive Tone** | Detects if the child is anxious, sad, or excited and adjusts the story accordingly |
| **Age-Adaptive Vocabulary** | `--age 5` through `--age 10` adjusts word complexity and story length |
| **Auto Technique Selection** | LLM-powered router picks the best generation strategy; user can override |
| **Closed-Loop Quality Control** | Judge agent scores stories on 4 dimensions; below-threshold stories get refined automatically |
| **Story Titles** | Every story gets a creative, child-friendly title |
| **Moral Extraction** | The lesson is extracted and displayed for parent-child discussion |
| **Story Continuation** | "What happens next?" generates a sequel with the same characters |
| **Surprise Mode** | `--surprise` generates a random story without any input |
| **Reading Time** | Estimates how long the story takes to read aloud (130 WPM for children) |
| **Cost Tracking** | Session summary shows API calls, tokens used, and estimated cost |
| **45 Tests** | Full test suite runs without an API key (all mocked) |

---

## System Architecture

```
                         ┌──────────────┐
                         │  USER INPUT  │
                         │  or --surprise│
                         └──────┬───────┘
                                │
                    ┌───────────▼───────────┐
                    │   INPUT VALIDATION    │
                    │   (strip, trim, reject)│
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   MOOD DETECTOR       │
                    │   calm/anxious/excited │
                    │   /sad/neutral         │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   CLASSIFIER          │
                    │   (3x self-consistency)│
                    │   → category           │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   PROMPT ROUTER       │
                    │   + user override      │
                    │   → technique          │
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
     ┌────────▼──────┐  ┌──────▼───────┐  ┌─────▼────────┐
     │   STANDARD    │  │  DECOMPOSE   │  │ SELF-CORRECT │
     │   (1 call)    │  │  (2 calls)   │  │  (2 calls)   │
     │   CoT only    │  │  plan→story  │  │  draft→fix   │
     └────────┬──────┘  └──────┬───────┘  └─────┬────────┘
              └─────────────────┼─────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │       JUDGE           │
                    │  vocabulary: ████░ 4/5│
                    │  engagement: █████ 5/5│
                    │  story_arc:  ████░ 4/5│
                    │  moral:      █████ 5/5│
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  >= 4.0? ──→ ACCEPT   │
                    │  < 4.0?  ──→ REFINE   │
                    │  (max 2 iterations)    │
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
     ┌────────▼──────┐  ┌──────▼───────┐  ┌─────▼────────┐
     │    TITLE      │  │    MORAL     │  │  CHARACTER   │
     │  GENERATOR    │  │  EXTRACTOR   │  │   MEMORY     │
     └────────┬──────┘  └──────┬───────┘  └─────┬────────┘
              └─────────────────┼─────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   DISPLAY STORY       │
                    │   + title + moral     │
                    │   + reading time      │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   POST-STORY MENU     │
                    │   [1] Changes         │
                    │   [2] Continue story  │
                    │   [Enter] Goodnight   │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   SESSION SUMMARY     │
                    │   calls/tokens/cost   │
                    └──────────────────────┘
```

---

## Agents

### Core Pipeline

| Agent | Role | Key Technique |
|---|---|---|
| **Classifier** | Maps request to one of 5 categories | Self-consistency: 3 calls, majority vote |
| **MoodDetector** | Detects child's emotional state | Zero-shot mood classification |
| **PromptRouter** | Selects optimal generation technique | Meta-prompting (LLM as router) |
| **Storyteller** | Generates the story (3 technique paths) | CoT + negative constraints + decompose/self-correct |
| **Judge** | Scores quality, provides feedback | Few-shot + rubric + structured JSON |

### Post-Processing

| Agent | Role | Key Technique |
|---|---|---|
| **TitleGenerator** | Creates a creative story title | Creative generation (temp=0.7) |
| **MoralExtractor** | Extracts the lesson in one sentence | Extraction prompting |
| **CharacterMemory** | Stores characters for continuation | Stateful memory + character extraction |

---

## Prompting Techniques

### Technique Map

```
┌─────────────────────────────────────────────────────────────────┐
│                    12 PROMPTING TECHNIQUES                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  CLASSIFICATION:                                                │
│    [1] Zero-shot classification                                 │
│    [2] Self-consistency (3x majority vote)                      │
│                                                                 │
│  GENERATION (always active):                                    │
│    [3] Role-based prompting (writer persona)                    │
│    [4] Chain-of-thought (silent planning step)                  │
│    [5] Negative constraints ("do NOT" rules)                    │
│                                                                 │
│  GENERATION (auto-selected):                                    │
│    [6] Least-to-most decomposition (plan → story)               │
│    [7] Self-correction (draft → review → rewrite)               │
│                                                                 │
│  REFINEMENT:                                                    │
│    [8] Feedback injection (Judge fixes → Storyteller)           │
│                                                                 │
│  EVALUATION:                                                    │
│    [9] Few-shot examples (calibration)                          │
│   [10] Scoring rubric (explicit 1/3/5 definitions)              │
│   [11] Structured JSON output                                   │
│                                                                 │
│  ROUTING:                                                       │
│   [12] Auto-mode selection (LLM as technique router)            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Why These Techniques?

| Technique | Problem It Solves |
|---|---|
| Self-consistency | Single classification calls occasionally misfire |
| Chain-of-thought | gpt-3.5-turbo produces more coherent stories when it plans first |
| Negative constraints | "Do NOT use violence" is more reliable than "try to avoid violence" |
| Least-to-most | Complex requests need explicit structure to avoid incoherence |
| Self-correction | Model can identify and fix its own weaknesses in a second pass |
| Feedback injection | Closes the quality loop — model sees exactly what to fix |
| Few-shot + rubric | Anchors scoring so "4/5" means the same thing every time |
| Auto-mode selection | LLM analyzes complexity better than hand-written heuristics |

### Why NOT These Techniques?

| Technique | Why Excluded |
|---|---|
| Tree-of-thought | Requires 3+ full stories generated and compared — too expensive |
| RAG (retrieval) | No knowledge base needed for creative fiction |
| Multi-persona debate | 4+ extra API calls for marginal quality gain |
| Few-shot story examples | Would consume context window, leaving less room for generation |

---

## Usage Examples

### Basic Usage
```bash
python3 main.py
# → "What kind of story would you like?"
# → Type: "a brave fox helps a lost firefly"
```

### Surprise Mode (no input needed)
```bash
python3 main.py --surprise
# → Picks a random creative prompt and generates a story
```

### Age-Adaptive (for a 5-year-old)
```bash
python3 main.py --age 5
# → Simpler words, shorter sentences, ~250 word stories
```

### Age-Adaptive (for a 10-year-old)
```bash
python3 main.py --age 10
# → Richer vocabulary, complex sentences, ~400 word stories
```

### Combined
```bash
python3 main.py --surprise --age 6
# → Random story with vocabulary appropriate for a 6-year-old
```

---

## How Quality is Ensured

The system uses a **closed-loop quality control** approach:

```
Generate Story → Judge Scores It → Score >= 4.0? → Accept
                                  → Score < 4.0? → Feed Fixes Back → Rewrite → Judge Again
```

### Scoring Dimensions

| Dimension | What "5" Means | What "1" Means |
|---|---|---|
| **Vocabulary** | All words under 3 syllables, short sentences | Adult-level vocabulary |
| **Engagement** | Vivid imagery, child would ask for it again | Boring or confusing |
| **Story Arc** | Clear beginning/middle/end, satisfying resolution | No structure |
| **Moral** | Positive lesson woven naturally | No lesson or inappropriate |

### Quality Safeguards

1. **Judge never crashes** — malformed JSON falls back to regex extraction, then retry, then default (accept story)
2. **Score recomputation** — we don't trust the model's arithmetic; overall is always recalculated in Python
3. **Best-story tracking** — if iteration 2 is worse than iteration 1, we keep iteration 1
4. **Graceful degradation** — if any agent fails, the pipeline continues with sensible defaults

---

## Design Decisions

| Decision | Rationale |
|---|---|
| **Judge agent** | Single-pass generators have no quality signal. The Judge provides structured feedback that drives targeted improvements. |
| **Mood detection** | A child who is anxious needs reassurance, not adventure. Demonstrates healthcare-adjacent thinking (relevant to Hippocratic AI). |
| **Age-adaptive vocabulary** | A 5-year-old needs "cat sat on mat" while a 10-year-old handles "the curious fox ventured through the enchanted forest." |
| **Story continuation** | Kids always want "one more chapter." Character memory enables sequels — shows stateful agent design. |
| **Decompose as default** | Every story benefits from explicit planning. Produces more coherent output than hoping CoT is enough. |
| **User technique override** | Automation with manual control. Power users experiment; casual users press Enter. |
| **Cap at 2 iterations** | Balances quality vs latency. gpt-3.5-turbo reliably hits >= 4.0 within 2 attempts. |
| **Token tracking** | Production awareness. Shows you think about real-world deployment costs. |

---

## Project Structure

```
.
├── main.py              Entry point, orchestration, --surprise, --age
├── agents.py            8 agent classes
├── prompts.py           All prompt templates (string constants only)
├── utils.py             Validation, parsing, display, retry, cost tracking
├── tests.py             45 unit + integration tests
├── .env.example         API key template
├── .gitignore           Python/IDE/OS exclusions
├── DESIGN.md            Full architecture documentation
├── REQUIREMENTS.md      Functional & non-functional requirements
├── TASKS.md             Implementation task breakdown
└── README.md            This file
```

### Code Organization Principles

- **prompts.py** — String constants only. No logic. Easy to review all prompts in one place.
- **agents.py** — Agent classes only. Each wraps one LLM call pattern.
- **utils.py** — Stateless helpers only. No agent logic, no prompt building.
- **main.py** — Orchestration only. Wires agents together in the correct order.

---

## Testing

```bash
# Run all 45 tests (no API key needed — all calls are mocked)
python3 tests.py
```

### Test Coverage

| Component | Tests | What's Covered |
|---|---|---|
| Input Validation | 7 | Empty, whitespace, trim, boundary, special chars |
| JSON Parsing | 7 | Clean, preamble, missing keys, garbage, markdown fences, recomputation |
| Score Display | 7 | Bar rendering, overflow, negative, pass/fail indicators |
| Environment Check | 3 | Missing key, empty key, valid key |
| Token Tracker | 4 | Initial state, recording, accumulation, summary format |
| Classifier | 4 | Valid category, invalid fallback, majority vote, all-invalid |
| PromptRouter | 5 | Standard, decompose, self_correct, invalid fallback, error degradation |
| Judge | 4 | Success, malformed retry, total failure default, score recomputation |
| Storyteller | 4 | Standard, decompose, self-correct, feedback injection |

---

## Example Output

```
Welcome to the Bedtime Story Generator!

What kind of story would you like? a brave fox helps a lost firefly find its way home

Detecting story mood...
  Detected mood: sad (adjusting story tone)

Classifying your story request...
  Category: Adventure

  Auto-selected technique: decompose
  Options: [1] standard  [2] decompose  [3] self_correct  [Enter] keep auto
  Select technique: 
  Using auto: decompose

Generating your story (attempt 1/2)...
  Technique: decompose

Evaluating story quality...

  --- Judge Evaluation (Round 1) ---
  Vocabulary:   █████  5/5
  Engagement:   █████  5/5
  Story Arc:    ████░  4/5
  Moral:        █████  5/5
  Overall:      4.8 / 5.0  PASS
  Story accepted.

Generating title and extracting moral...

─────────────────────────────────────────────
  "Finn and the Lost Firefly"
─────────────────────────────────────────────
In the heart of Whispering Woods, there lived a little fox named Finn
with the softest red fur and the brightest curious eyes. Every evening,
Finn loved to watch the fireflies dance above the meadow like tiny
floating lanterns.

One night, Finn heard a tiny voice. "Help! I'm lost!" It was a small
firefly named Luna, her glow flickering with worry. She had flown too
far from home and now the dark forest seemed so big.

"Don't worry," said Finn gently. "I'll help you find your way."

Together they set off through the woods. Finn used his sharp nose to
sniff out the safest paths, while Luna's soft light guided them around
the puddles and roots. When they reached a fork in the trail, Finn
almost gave up — but then he remembered what his mother always said:
"When you're lost, follow the sound of water."

They followed a tiny stream, and soon Luna cried, "I see them! My
family!" Dozens of fireflies blinked in the distance like a field of
tiny stars.

Luna hugged Finn's nose. "Thank you for being brave for me."

Finn smiled. "Sometimes being brave just means taking the next step."

He padded home through the quiet woods, feeling warm inside. As he
curled up in his cozy den, the last thing he saw was a single firefly
blinking outside his window — Luna, saying goodnight.

And under a blanket of stars, Finn drifted off to sleep.
─────────────────────────────────────────────
  Reading time: ~3 min (312 words)
  Lesson: "Being brave means helping others even when the path is uncertain."

What would you like to do next?
  [1] Request changes (e.g. 'make it funnier', 'add a dragon')
  [2] Continue the story ('what happens next?')
  [Enter] Finish and say goodnight
  Your choice: 

Sweet dreams! Goodnight.

Session Stats: 9 API calls | ~4,100 tokens | Est. cost: $0.0072
```

---

## Cost Estimate

| Run Type | API Calls | Tokens | Cost |
|---|---|---|---|
| Simple (first pass accepted) | ~9 | ~4,000 | ~$0.007 |
| With refinement (2 iterations) | ~12 | ~6,000 | ~$0.010 |
| With user feedback revision | ~13 | ~7,500 | ~$0.012 |
| With story continuation | ~15 | ~9,000 | ~$0.015 |

All costs are estimates based on gpt-3.5-turbo pricing (~$0.0015/1K prompt, ~$0.002/1K completion).

---

## What I Would Build Next (2 more hours)

1. **Persistent Memory** — Vector-DB-backed storage of past stories and user preferences for personalized storytelling across sessions.
2. **A/B Testing** — Empirically measure which technique produces higher Judge scores per category, then update the PromptRouter with real data.
3. **Safety Classifier** — Pre-filter agent that screens inputs for inappropriate content with soft-redirect instead of hard-block.
4. **Streaming Output** — Word-by-word display for a "being told a story" experience.
5. **Voice Output** — Text-to-speech integration so the story can be read aloud.

---

*Built as a take-home assignment for Hippocratic AI.*
