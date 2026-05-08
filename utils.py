"""
utils.py — Stateless helper functions for the Bedtime Story Generator.

This module contains:
- TokenTracker: API call and cost tracking for production observability
- validate_input(): User input sanitization and validation
- parse_judge_json(): Robust JSON extraction from LLM output
- call_model_with_retry(): Resilient API wrapper with retry logic
- Display helpers: print_story(), print_scores(), show_progress()
- check_api_key(): Environment validation at startup
- estimate_reading_time(): Story length estimation for parents

Design principle: No agent logic or prompt building lives here.
All functions are pure/stateless except the global tracker instance.
"""

import os
import sys
import json
import re
import time
from typing import Dict, Optional


# ===========================================================================
# TOKEN / API CALL TRACKING
# ===========================================================================


class TokenTracker:
    """
    Tracks API call count and estimates token usage across the pipeline.

    Why this exists:
    - Production awareness: developers and users can see the cost of each session
    - Debugging: helps identify if a pipeline path is making too many calls
    - Cost estimation: approximate pricing based on gpt-3.5-turbo rates

    Token estimation uses the ~4 chars/token heuristic for English text.
    For exact counts, you'd use tiktoken — but this is sufficient for a CLI tool.
    """

    # gpt-3.5-turbo pricing (approximate as of 2024)
    PROMPT_COST_PER_1K: float = 0.0015
    COMPLETION_COST_PER_1K: float = 0.002

    def __init__(self) -> None:
        self.api_calls: int = 0
        self.estimated_prompt_tokens: int = 0
        self.estimated_completion_tokens: int = 0

    def record_call(self, prompt: str, response: str, max_tokens: int) -> None:
        """
        Record an API call with estimated token counts.

        Args:
            prompt: The full prompt string sent to the model.
            response: The model's response string.
            max_tokens: The max_tokens parameter (unused in estimation, kept for future use).
        """
        self.api_calls += 1
        # Rough estimate: 1 token ≈ 4 characters for English text
        self.estimated_prompt_tokens += len(prompt) // 4
        self.estimated_completion_tokens += len(response) // 4

    @property
    def total_tokens(self) -> int:
        """Total estimated tokens (prompt + completion) across all calls."""
        return self.estimated_prompt_tokens + self.estimated_completion_tokens

    def summary(self) -> str:
        """
        Return a formatted cost summary string for end-of-session display.

        Example output:
            Session Stats: 7 API calls | ~3,200 tokens | Est. cost: $0.0053
        """
        prompt_cost = (self.estimated_prompt_tokens / 1000) * self.PROMPT_COST_PER_1K
        completion_cost = (self.estimated_completion_tokens / 1000) * self.COMPLETION_COST_PER_1K
        total_cost = prompt_cost + completion_cost
        return (
            f"Session Stats: {self.api_calls} API calls | "
            f"~{self.total_tokens:,} tokens (prompt: ~{self.estimated_prompt_tokens:,}, "
            f"completion: ~{self.estimated_completion_tokens:,}) | "
            f"Est. cost: ${total_cost:.4f}"
        )


# Global tracker instance — shared across all modules in a single session
tracker = TokenTracker()


# ===========================================================================
# INPUT VALIDATION
# ===========================================================================


def validate_input(text: str) -> str:
    """
    Sanitize and validate user input for the story request.

    Rules:
        1. Strip leading/trailing whitespace
        2. Reject empty input with a friendly error message
        3. Trim to 500 characters if too long (with user notification)

    Args:
        text: Raw user input string from CLI.

    Returns:
        Cleaned, validated input string (max 500 chars).

    Raises:
        ValueError: If input is empty or whitespace-only.
    """
    text = text.strip()

    if not text:
        raise ValueError("Please tell me what kind of story you'd like!")

    if len(text) > 500:
        print("  (Your input was trimmed to 500 characters)")
        text = text[:500]

    return text


# ===========================================================================
# JSON PARSING (for Judge output)
# ===========================================================================

# Keys that MUST be present in a valid Judge response
REQUIRED_KEYS: set = {
    "vocabulary_score",
    "engagement_score",
    "story_arc_score",
    "moral_score",
    "feedback",
    "specific_fixes",
}


def parse_judge_json(text: str) -> Dict:
    """
    Parse the Judge's JSON response with multiple fallback strategies.

    Strategy:
        1. Try direct json.loads() — works when model follows instructions perfectly
        2. Regex extraction — finds first '{' to last '}' in case of preamble text
        3. Raise ValueError if both fail — caller handles retry logic

    After parsing, validates all required keys exist and recomputes the
    overall score as the average of the four dimension scores (in case
    the model computed it incorrectly).

    Args:
        text: Raw string response from the Judge LLM call.

    Returns:
        Dict with all required keys + computed 'overall' score.

    Raises:
        ValueError: If JSON cannot be parsed or required keys are missing.
    """
    data: Optional[Dict] = None

    # Strategy 1: Direct parse (ideal case)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: Regex extraction (handles preamble, markdown fences, etc.)
    if data is None:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                pass

    # Both strategies failed
    if data is None:
        raise ValueError("Could not parse Judge response as JSON")

    # Validate all required keys are present
    missing = REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Judge JSON missing keys: {missing}")

    # Recompute overall score as average of the four dimensions
    # This guards against the model returning an incorrect average
    scores = [
        data["vocabulary_score"],
        data["engagement_score"],
        data["story_arc_score"],
        data["moral_score"],
    ]
    computed = round(sum(scores) / len(scores), 1)

    # Override if missing or significantly wrong (tolerance: 0.1)
    if "overall" not in data or abs(data.get("overall", 0) - computed) > 0.1:
        data["overall"] = computed

    return data


# ===========================================================================
# API WRAPPER WITH RETRY LOGIC
# ===========================================================================


def call_model_with_retry(
    prompt: str,
    max_tokens: int = 3000,
    temperature: float = 0.1,
) -> str:
    """
    Resilient wrapper around call_model() with error handling and retry logic.

    Error handling strategy:
        - RateLimitError: Wait 5 seconds, retry once (transient issue)
        - APIError / Timeout: Print error, exit (infrastructure issue)
        - Empty response: Retry once, then raise ValueError
        - Any other exception: Print error, exit (unexpected failure)

    Also records each successful call to the global TokenTracker for
    cost monitoring.

    Args:
        prompt: The full prompt string to send to the model.
        max_tokens: Maximum tokens in the model's response.
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).

    Returns:
        The model's response string (guaranteed non-empty).

    Raises:
        ValueError: If model returns empty response after retry.
        SystemExit: On unrecoverable API errors.
    """
    # Import here to avoid circular imports at module load time
    # (main.py imports from utils.py, utils.py imports call_model from main.py)
    from main import call_model
    import openai

    def _call() -> str:
        """Single API call — extracted for DRY retry logic."""
        return call_model(prompt, max_tokens=max_tokens, temperature=temperature)

    # --- Attempt the API call with error handling ---
    try:
        result = _call()
    except openai.RateLimitError:
        # Transient: wait and retry once
        print("  Rate limit hit — waiting 5 seconds...")
        time.sleep(5)
        try:
            result = _call()
        except openai.RateLimitError:
            print("  ERROR: Rate limit persists after retry. Please try again later.")
            sys.exit(1)
    except (openai.APIError, openai.APITimeoutError) as e:
        # Infrastructure issue: cannot recover
        print(f"  ERROR: OpenAI API error: {e}")
        sys.exit(1)
    except Exception as e:
        # Unexpected: log and exit
        print(f"  ERROR: Unexpected error: {e}")
        sys.exit(1)

    # --- Handle empty response (model returned nothing) ---
    if not result or not result.strip():
        try:
            result = _call()
        except Exception as e:
            print(f"  ERROR: Unexpected error on retry: {e}")
            sys.exit(1)
        if not result or not result.strip():
            raise ValueError("Empty response from model after retry")

    # --- Track token usage for cost monitoring ---
    tracker.record_call(prompt, result, max_tokens)

    return result


# ===========================================================================
# DISPLAY HELPERS
# ===========================================================================

# Visual separator for story display
_SEPARATOR: str = "─" * 45

# Average reading speed for children ages 5-10 (words per minute)
_CHILD_READING_WPM: int = 130


def print_story(story: str, title: str = "", moral: str = "") -> None:
    """
    Print the final story with title, decorative header, moral, and reading time.

    Args:
        story: The complete story text to display.
        title: Optional creative title for the story.
        moral: Optional moral/lesson extracted from the story.
    """
    print(f"\n{_SEPARATOR}")
    if title:
        print(f"  \"{title}\"")
        print(_SEPARATOR)
    else:
        print("YOUR STORY")
        print(_SEPARATOR)
    print(story)
    print(_SEPARATOR)

    # Reading time estimation — useful for parents planning bedtime
    reading_time = estimate_reading_time(story)
    word_count = len(story.split())
    print(f"  Reading time: ~{reading_time} min ({word_count} words)")

    # Moral/lesson — helps parents discuss the story with their child
    if moral:
        print(f"  Lesson: \"{moral}\"")


def estimate_reading_time(text: str) -> int:
    """
    Estimate reading time in minutes for a children's bedtime story.

    Uses 130 WPM (average for children ages 5-10 being read to).
    Minimum 1 minute.

    Args:
        text: The story text.

    Returns:
        Estimated reading time in minutes (minimum 1).
    """
    word_count = len(text.split())
    minutes = max(1, round(word_count / _CHILD_READING_WPM))
    return minutes


def _bar(score: int, total: int = 5) -> str:
    """
    Generate a visual block progress bar for score display.

    Examples:
        _bar(4) → '████░'
        _bar(2) → '██░░░'
        _bar(5) → '█████'

    Args:
        score: The score value (clamped to 0-total range).
        total: Maximum score (default 5).

    Returns:
        String of filled (█) and empty (░) blocks.
    """
    filled = max(0, min(score, total))
    return "█" * filled + "░" * (total - filled)


def print_scores(result: Dict, iteration: int) -> None:
    """
    Print a formatted score table with visual block bars.

    Output format:
        --- Judge Evaluation (Round 1) ---
        Vocabulary:   ████░  4/5
        Engagement:   ███░░  3/5
        Story Arc:    █████  5/5
        Moral:        ████░  4/5
        Overall:      4.0 / 5.0  PASS

    The PASS indicator appears when overall >= 4.0 (story accepted).
    The NEEDS WORK indicator appears when overall < 4.0 (needs refinement).

    Args:
        result: Dict containing all score keys and 'overall'.
        iteration: Current refinement loop iteration number.
    """
    v = result.get("vocabulary_score", 0)
    e = result.get("engagement_score", 0)
    s = result.get("story_arc_score", 0)
    m = result.get("moral_score", 0)
    overall = result.get("overall", 0.0)

    # Visual indicator: pass or needs work
    indicator = "PASS" if overall >= 4.0 else "NEEDS WORK"

    print(f"\n  --- Judge Evaluation (Round {iteration}) ---")
    print(f"  Vocabulary:   {_bar(v)}  {v}/5")
    print(f"  Engagement:   {_bar(e)}  {e}/5")
    print(f"  Story Arc:    {_bar(s)}  {s}/5")
    print(f"  Moral:        {_bar(m)}  {m}/5")
    print(f"  Overall:      {overall:.1f} / 5.0  {indicator}")


def show_progress(message: str) -> None:
    """
    Print a progress message before an API call.

    Keeps the user informed during potentially slow LLM calls.
    No threading or animation — just a simple print.

    Args:
        message: The progress message to display (e.g., "Generating your story...").
    """
    print(f"\n{message}")


# ===========================================================================
# ENVIRONMENT CHECK
# ===========================================================================


def check_api_key() -> None:
    """
    Validate that OPENAI_API_KEY is set in the environment.

    Called at startup before any API calls. Exits with a clear,
    actionable error message if the key is missing.

    Exits:
        sys.exit(1) if OPENAI_API_KEY is not set or empty.
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY environment variable is not set.")
        print("   Run: export OPENAI_API_KEY=your_key_here")
        print("   Get your key at: https://platform.openai.com/api-keys")
        sys.exit(1)
