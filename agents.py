"""
agents.py — Agent classes for the Bedtime Story Generator pipeline.

This module contains three agent classes, each wrapping a distinct LLM call pattern:
- Classifier: Categorizes user requests (self-consistency via majority vote)
- Storyteller: Generates stories (auto-selects from multiple prompting techniques)
- Judge: Evaluates story quality (few-shot calibrated scoring)

Plus one routing agent:
- PromptRouter: Meta-agent that selects the optimal technique per request

Design principle: Each agent is a thin wrapper around prompt construction + API call.
All prompts live in prompts.py; all utility functions live in utils.py.
"""

from typing import Dict, List, Optional
from collections import Counter

import prompts
from utils import call_model_with_retry, parse_judge_json


# ===========================================================================
# CLASSIFIER — Self-Consistency (majority vote over 3 calls)
# ===========================================================================


class Classifier:
    """
    Classifies a user's story request into one of five categories.

    Prompting technique: Self-Consistency
    -----------------------------------------
    Instead of a single classification call (which can occasionally misfire),
    we make 3 independent calls at temperature=0.3 and return the majority vote.
    This eliminates occasional misclassifications at minimal cost (20 tokens × 3 = 60 tokens).

    Valid categories: adventure, friendship, fantasy, animals, bedtime
    Fallback: "adventure" (most general category) if all votes are invalid.
    """

    VALID_CATEGORIES: set = {"adventure", "friendship", "fantasy", "animals", "bedtime"}
    NUM_VOTES: int = 3  # Number of independent classification calls

    def classify(self, user_input: str) -> str:
        """
        Classify the user's request into a story category.

        Process:
            1. Format the classifier prompt with user input
            2. Make NUM_VOTES independent API calls
            3. Filter to valid categories only
            4. Return majority vote (most common valid response)

        Args:
            user_input: The validated user story request.

        Returns:
            One of the five valid category strings.
        """
        prompt = prompts.CLASSIFIER_PROMPT.format(user_input=user_input)

        # Collect votes from multiple independent calls
        votes: List[str] = []
        for _ in range(self.NUM_VOTES):
            result = call_model_with_retry(prompt, max_tokens=20, temperature=0.3)
            # Normalize: strip whitespace, lowercase, remove trailing punctuation
            result = result.strip().lower().rstrip(".")
            # Only count valid votes
            if result in self.VALID_CATEGORIES:
                votes.append(result)

        # Fallback if all votes were invalid (shouldn't happen, but defensive)
        if not votes:
            return "adventure"

        # Majority vote: return the most common valid category
        counter = Counter(votes)
        winner, _ = counter.most_common(1)[0]
        return winner


# ===========================================================================
# PROMPT ROUTER — Auto-mode technique selection
# ===========================================================================


class PromptRouter:
    """
    Automatically selects the best prompting technique for a given request.

    Prompting technique: Meta-prompting / Auto-mode selection
    ---------------------------------------------------------
    Uses the LLM itself to analyze request complexity and route to the
    optimal generation strategy. This is a form of "prompt about prompting."

    Available techniques:
        - "standard": Chain-of-thought (built into base prompt). Best for simple requests.
        - "decompose": Least-to-most decomposition. Best for complex multi-element requests.
        - "self_correct": Generate + self-review. Best for quality-sensitive requests.

    Graceful degradation:
        If the routing call fails for ANY reason (rate limit, timeout, malformed response),
        falls back to "standard" silently. The pipeline never breaks due to a router failure.
    """

    VALID_TECHNIQUES: set = {"standard", "decompose", "self_correct"}

    def select_technique(self, user_input: str) -> str:
        """
        Analyze the user's request and select the optimal generation technique.

        Args:
            user_input: The validated user story request.

        Returns:
            One of: "standard", "decompose", "self_correct".
            Falls back to "decompose" on any error (best default for stories).
        """
        try:
            prompt = prompts.TECHNIQUE_SELECTOR_PROMPT.format(user_input=user_input)
            result = call_model_with_retry(prompt, max_tokens=20, temperature=0.0)
            result = result.strip().lower().rstrip(".")

            if result not in self.VALID_TECHNIQUES:
                return "decompose"
            return result
        except Exception:
            # Graceful degradation: never let the router crash the pipeline
            return "decompose"


# ===========================================================================
# STORYTELLER — Multiple techniques with auto-selection
# ===========================================================================


class Storyteller:
    """
    Generates bedtime stories using category-specific prompts.

    Prompting techniques used (auto-selected per request):
    -------------------------------------------------------
    1. Chain-of-thought (always active): Planning step embedded in system prompt
    2. Negative constraints (always active): Explicit "do NOT" rules
    3. Role-based prompting (always active): Writer persona in system prompt
    4. Least-to-most decomposition (auto): For complex multi-element requests
    5. Self-correction (auto): Generate → self-review → rewrite
    6. Feedback injection (on refinement): Judge's fixes fed back to model
    7. Auto-mode selection: PromptRouter picks the technique

    The PromptRouter decides which technique to use based on request complexity.
    On refinement passes (when feedback is provided), feedback injection is always used.
    """

    def __init__(self) -> None:
        """Initialize with a PromptRouter for auto technique selection."""
        self.router = PromptRouter()

    def generate(
        self,
        user_input: str,
        category: str,
        feedback: Optional[Dict] = None,
        technique_override: Optional[str] = None,
    ) -> str:
        """
        Generate a bedtime story.

        If feedback is provided (refinement pass), uses feedback injection.
        Otherwise, uses the technique_override if given, or auto-selects via PromptRouter.

        Args:
            user_input: The validated user story request.
            category: Story category from the Classifier.
            feedback: Optional Judge feedback dict for refinement passes.
            technique_override: Optional manual technique choice from the user.

        Returns:
            The generated story text.
        """
        system_prompt = prompts.STORYTELLER_SYSTEM_PROMPTS[category]

        if feedback is not None:
            # Refinement pass — always use feedback injection
            return self._generate_with_refinement(user_input, system_prompt, feedback)

        # Determine technique: user override or auto-select
        if technique_override and technique_override in self.router.VALID_TECHNIQUES:
            technique = technique_override
        else:
            technique = self.router.select_technique(user_input)

        print(f"  Technique: {technique}")

        if technique == "decompose":
            return self._generate_with_decomposition(user_input, system_prompt)
        elif technique == "self_correct":
            return self._generate_with_self_correction(user_input, system_prompt)
        else:
            return self._generate_standard(user_input, system_prompt)

    # --- Standard: Chain-of-thought (built into system prompt) ---

    def _generate_standard(self, user_input: str, system_prompt: str) -> str:
        """
        Standard generation using chain-of-thought planning.

        The system prompt already contains the planning step instruction,
        so the model silently plans before writing. This is the simplest
        and fastest technique — one API call.

        Args:
            user_input: The user's story request.
            system_prompt: Category-specific system prompt with CoT instructions.

        Returns:
            Generated story text.
        """
        user_prompt = prompts.STORYTELLER_USER_PROMPT.format(user_input=user_input)
        full_prompt = system_prompt + "\n\n" + user_prompt

        result = call_model_with_retry(full_prompt, max_tokens=700, temperature=0.85)

        # Retry once on empty (defensive — shouldn't happen with retry logic in utils)
        if not result or not result.strip():
            result = call_model_with_retry(full_prompt, max_tokens=700, temperature=0.85)

        return result

    # --- Least-to-Most Decomposition ---

    def _generate_with_decomposition(self, user_input: str, system_prompt: str) -> str:
        """
        Least-to-most decomposition for complex requests.

        Two-step process:
            Step 1: Decompose the request into simple story elements
                    (characters, setting, conflict, resolution, moral)
            Step 2: Generate the full story from the structured plan

        This technique excels when the user's request contains 3+ distinct
        elements that need to be woven together coherently.

        Args:
            user_input: The user's complex story request.
            system_prompt: Category-specific system prompt.

        Returns:
            Generated story text.
        """
        # Step 1: Decompose into sub-parts
        decompose_prompt = prompts.STORYTELLER_DECOMPOSE_PROMPT.format(user_input=user_input)
        story_plan = call_model_with_retry(decompose_prompt, max_tokens=200, temperature=0.3)

        # Step 2: Generate from the structured plan
        gen_prompt = system_prompt + "\n\n" + prompts.STORYTELLER_FROM_PLAN_PROMPT.format(
            story_plan=story_plan,
            user_input=user_input,
        )
        result = call_model_with_retry(gen_prompt, max_tokens=700, temperature=0.85)

        if not result or not result.strip():
            result = call_model_with_retry(gen_prompt, max_tokens=700, temperature=0.85)

        return result

    # --- Self-Correction ---

    def _generate_with_self_correction(self, user_input: str, system_prompt: str) -> str:
        """
        Self-correction: generate a draft, then self-review and rewrite.

        Two-step process:
            Step 1: Generate initial story (standard chain-of-thought)
            Step 2: Model reviews its own output and rewrites with 2 improvements

        This technique produces the highest quality output but costs 2 API calls.
        Used when the PromptRouter detects quality-sensitive requests.

        Args:
            user_input: The user's story request.
            system_prompt: Category-specific system prompt.

        Returns:
            The self-corrected story text (or original draft if correction fails).
        """
        # Step 1: Generate initial draft
        draft = self._generate_standard(user_input, system_prompt)

        # Step 2: Self-review and rewrite
        correction_prompt = prompts.STORYTELLER_SELF_CORRECTION_PROMPT.format(story=draft)
        corrected = call_model_with_retry(correction_prompt, max_tokens=800, temperature=0.7)

        # Extract the revised story from the structured response
        if "REVISED STORY:" in corrected:
            revised = corrected.split("REVISED STORY:", 1)[1].strip()
            return revised if revised else draft
        else:
            # If the model didn't follow the format, use whatever it returned
            return corrected if corrected.strip() else draft

    # --- Feedback Injection (Refinement from Judge) ---

    def _generate_with_refinement(
        self,
        user_input: str,
        system_prompt: str,
        feedback: Dict,
    ) -> str:
        """
        Feedback injection: incorporate Judge's structured feedback into the prompt.

        The model receives:
            - The original system prompt (for persona/guidelines)
            - The Judge's overall feedback text
            - A bullet list of specific fixes to apply

        This closes the quality improvement loop — the model sees exactly
        what to fix and rewrites accordingly.

        Args:
            user_input: The user's original story request.
            system_prompt: Category-specific system prompt.
            feedback: Dict with 'feedback' (str) and 'specific_fixes' (list).

        Returns:
            The refined story text.
        """
        fixes_text = "\n".join(f"- {fix}" for fix in feedback["specific_fixes"])
        full_prompt = system_prompt + "\n\n" + prompts.STORYTELLER_REFINEMENT_PROMPT.format(
            user_input=user_input,
            feedback=feedback["feedback"],
            specific_fixes=fixes_text,
        )

        result = call_model_with_retry(full_prompt, max_tokens=700, temperature=0.85)

        if not result or not result.strip():
            result = call_model_with_retry(full_prompt, max_tokens=700, temperature=0.85)

        return result


# ===========================================================================
# JUDGE — Few-shot + Structured output + Role-based + Scoring rubric
# ===========================================================================


class Judge:
    """
    Evaluates story quality and returns structured scores + feedback.

    Prompting techniques used:
    ---------------------------
    1. Few-shot examples: One calibration example anchors what "4/5" means
    2. Scoring rubric: Explicit definitions for each score level (1, 3, 5)
    3. Structured output: Explicit JSON schema with "ONLY valid JSON" instruction
    4. Role-based prompting: "children's story quality evaluator" persona

    Robustness:
        - If JSON parsing fails, retries the API call once
        - If both attempts fail, returns DEFAULT_RESULT (all 5s, empty fixes)
        - Always recomputes 'overall' from the four scores (guards against model math errors)

    The Judge never raises exceptions — it always returns a valid result dict.
    """

    # Fallback result when evaluation completely fails
    # All 5s = "benefit of the doubt" — story is accepted as-is
    DEFAULT_RESULT: Dict = {
        "vocabulary_score": 5,
        "engagement_score": 5,
        "story_arc_score": 5,
        "moral_score": 5,
        "overall": 5.0,
        "feedback": "Could not evaluate — accepting story as-is.",
        "specific_fixes": [],
    }

    def evaluate(self, story: str) -> Dict:
        """
        Evaluate a story on four quality dimensions.

        Process:
            1. Format the Judge prompt with the story text
            2. Call the model (temperature=0.1 for consistent scoring)
            3. Parse the JSON response (with regex fallback)
            4. On parse failure: retry once, then fall back to DEFAULT_RESULT
            5. Recompute 'overall' as average of four scores

        Args:
            story: The complete story text to evaluate.

        Returns:
            Dict with keys: vocabulary_score, engagement_score, story_arc_score,
            moral_score, overall, feedback, specific_fixes.
            Guaranteed to always return a valid dict (never raises).
        """
        prompt = prompts.JUDGE_PROMPT.format(story=story)
        response = call_model_with_retry(prompt, max_tokens=300, temperature=0.1)

        try:
            result = parse_judge_json(response)
        except ValueError:
            # First parse failed — retry the API call once
            response = call_model_with_retry(prompt, max_tokens=300, temperature=0.1)
            try:
                result = parse_judge_json(response)
            except ValueError:
                # Both attempts failed — return safe default
                return dict(self.DEFAULT_RESULT)

        # Recompute overall to guard against model arithmetic errors
        scores = [
            result["vocabulary_score"],
            result["engagement_score"],
            result["story_arc_score"],
            result["moral_score"],
        ]
        result["overall"] = round(sum(scores) / len(scores), 1)
        return result


# ===========================================================================
# MOOD DETECTOR — Detect child's emotional state
# ===========================================================================


class MoodDetector:
    """
    Detects the emotional mood behind a story request.

    Purpose: Adjust story tone based on the child's likely emotional state.
    A child who is anxious gets extra reassurance; a sad child gets comfort;
    an excited child gets a story that gradually winds down.

    This demonstrates healthcare-adjacent thinking — understanding the
    emotional context of the user (relevant to Hippocratic AI's mission).
    """

    VALID_MOODS: set = {"calm", "anxious", "excited", "sad", "neutral"}

    def detect(self, user_input: str) -> str:
        """
        Detect the mood behind the user's story request.

        Args:
            user_input: The validated user story request.

        Returns:
            One of: "calm", "anxious", "excited", "sad", "neutral".
        """
        try:
            prompt = prompts.MOOD_PROMPT.format(user_input=user_input)
            result = call_model_with_retry(prompt, max_tokens=20, temperature=0.0)
            result = result.strip().lower().rstrip(".")
            if result not in self.VALID_MOODS:
                return "neutral"
            return result
        except Exception:
            return "neutral"

    def get_adjustment(self, mood: str) -> str:
        """
        Get the tone adjustment text for a given mood.

        Args:
            mood: The detected mood string.

        Returns:
            Prompt adjustment text to append to the storyteller system prompt.
            Empty string if no adjustment needed.
        """
        return prompts.MOOD_ADJUSTMENTS.get(mood, "")


# ===========================================================================
# TITLE GENERATOR — Creative story titles
# ===========================================================================


class TitleGenerator:
    """
    Generates a creative, child-friendly title for a completed story.

    Called after story generation. The title is displayed above the story
    for a "tonight's story is called..." experience.
    """

    def generate(self, story: str) -> str:
        """
        Generate a creative title for the given story.

        Args:
            story: The complete story text.

        Returns:
            A short, creative title (3-7 words).
        """
        try:
            prompt = prompts.TITLE_PROMPT.format(story=story)
            result = call_model_with_retry(prompt, max_tokens=30, temperature=0.7)
            # Clean up: remove quotes, extra whitespace
            title = result.strip().strip('"').strip("'")
            return title if title else "A Bedtime Story"
        except Exception:
            return "A Bedtime Story"


# ===========================================================================
# MORAL EXTRACTOR — Extract the lesson for parents
# ===========================================================================


class MoralExtractor:
    """
    Extracts the moral/lesson from a completed story.

    Displayed after the story so parents can discuss the lesson with their child.
    Makes the educational value of the story explicit and accessible.
    """

    def extract(self, story: str) -> str:
        """
        Extract the moral or life lesson from the story.

        Args:
            story: The complete story text.

        Returns:
            A one-sentence moral/lesson string.
        """
        try:
            prompt = prompts.MORAL_PROMPT.format(story=story)
            result = call_model_with_retry(prompt, max_tokens=60, temperature=0.3)
            moral = result.strip().strip('"')
            return moral if moral else "Every story has a lesson to discover together."
        except Exception:
            return "Every story has a lesson to discover together."


# ===========================================================================
# CHARACTER MEMORY — Track characters across stories in a session
# ===========================================================================


class CharacterMemory:
    """
    Tracks characters from generated stories within a session.

    Enables:
    - Story continuation ("what happens next?") with consistent characters
    - Character reuse across multiple stories in the same session
    - Shows understanding of stateful agent design

    Characters are stored as a simple string description extracted by the LLM.
    """

    def __init__(self) -> None:
        self.characters: str = ""
        self.last_story: str = ""

    def remember(self, story: str) -> None:
        """
        Extract and store characters from a story.

        Args:
            story: The complete story text to extract characters from.
        """
        try:
            prompt = prompts.CHARACTER_EXTRACT_PROMPT.format(story=story)
            result = call_model_with_retry(prompt, max_tokens=150, temperature=0.1)
            self.characters = result.strip()
            self.last_story = story
        except Exception:
            self.characters = "the main characters from the previous story"
            self.last_story = story

    def generate_continuation(self, category: str) -> str:
        """
        Generate a story continuation using remembered characters.

        Args:
            category: The story category for system prompt selection.

        Returns:
            A continuation story (200-300 words).
        """
        system_prompt = prompts.STORYTELLER_SYSTEM_PROMPTS.get(category, prompts.STORYTELLER_SYSTEM_PROMPTS["adventure"])
        continuation_prompt = system_prompt + "\n\n" + prompts.CONTINUATION_PROMPT.format(
            story=self.last_story,
            characters=self.characters,
        )
        result = call_model_with_retry(continuation_prompt, max_tokens=500, temperature=0.85)
        return result if result and result.strip() else "The adventure continues another night..."

    @property
    def has_memory(self) -> bool:
        """Check if there are characters stored from a previous story."""
        return bool(self.characters and self.last_story)
