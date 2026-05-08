"""
tests.py — Unit and integration tests for the Bedtime Story Generator.

Run with: python3 tests.py
No external test framework needed — uses unittest from stdlib.

Tests are organized by component:
- TestInputValidation: Edge cases for user input handling
- TestJudgeJsonParsing: Robustness of JSON extraction from LLM output
- TestScoreDisplay: Visual output formatting
- TestEnvironmentCheck: API key validation
- TestTokenTracker: Cost tracking accuracy
- TestClassifier: Category classification with mocked API
- TestPromptRouter: Technique selection with mocked API
- TestJudge: Evaluation pipeline with mocked API
- TestStoryteller: Story generation with mocked API
"""

import unittest
import sys
import os
import json
from unittest.mock import patch, MagicMock
from io import StringIO

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    validate_input,
    parse_judge_json,
    print_scores,
    print_story,
    show_progress,
    check_api_key,
    TokenTracker,
    tracker,
    _bar,
)


# ===========================================================================
# UNIT TESTS (no API calls needed)
# ===========================================================================


class TestInputValidation(unittest.TestCase):
    """Edge cases for validate_input()."""

    def test_empty_string_raises(self):
        """Case 1: Empty input should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            validate_input("")
        self.assertIn("Please tell me what kind of story", str(ctx.exception))

    def test_whitespace_only_raises(self):
        """Case 2: Whitespace-only input should raise ValueError."""
        with self.assertRaises(ValueError):
            validate_input("   \t\n  ")

    def test_long_input_trimmed(self):
        """Case 3: Input > 500 chars should be trimmed."""
        long_input = "a" * 600
        with patch("sys.stdout", new_callable=StringIO):
            result = validate_input(long_input)
        self.assertEqual(len(result), 500)

    def test_normal_input_returned(self):
        """Case 4: Normal input returned stripped."""
        result = validate_input("  hello world  ")
        self.assertEqual(result, "hello world")

    def test_special_characters(self):
        """Case 5: Special chars and emojis don't crash."""
        result = validate_input("A story with \U0001f98a and \u2b50 and <special> chars!")
        self.assertIn("\U0001f98a", result)

    def test_exactly_500_chars(self):
        """Boundary: exactly 500 chars should NOT be trimmed."""
        input_500 = "x" * 500
        result = validate_input(input_500)
        self.assertEqual(len(result), 500)

    def test_501_chars_trimmed(self):
        """Boundary: 501 chars should be trimmed to 500."""
        input_501 = "x" * 501
        with patch("sys.stdout", new_callable=StringIO):
            result = validate_input(input_501)
        self.assertEqual(len(result), 500)


class TestJudgeJsonParsing(unittest.TestCase):
    """Robustness of parse_judge_json()."""

    def test_clean_json(self):
        """Case 14: Clean JSON parses correctly."""
        data = {
            "vocabulary_score": 4,
            "engagement_score": 5,
            "story_arc_score": 4,
            "moral_score": 5,
            "overall": 4.5,
            "feedback": "Great story!",
            "specific_fixes": [],
        }
        result = parse_judge_json(json.dumps(data))
        self.assertEqual(result["vocabulary_score"], 4)
        self.assertEqual(result["overall"], 4.5)

    def test_json_with_preamble(self):
        """Case 15: JSON wrapped in text is extracted via regex."""
        text = 'Here is my evaluation:\n{"vocabulary_score": 3, "engagement_score": 4, "story_arc_score": 3, "moral_score": 4, "overall": 3.5, "feedback": "OK", "specific_fixes": ["fix1"]}\nDone!'
        result = parse_judge_json(text)
        self.assertEqual(result["vocabulary_score"], 3)

    def test_missing_keys_raises(self):
        """Case 16: Missing required keys raises ValueError."""
        incomplete = '{"vocabulary_score": 5, "engagement_score": 5}'
        with self.assertRaises(ValueError) as ctx:
            parse_judge_json(incomplete)
        self.assertIn("missing keys", str(ctx.exception))

    def test_garbage_raises(self):
        """Case 17: Non-JSON garbage raises ValueError."""
        with self.assertRaises(ValueError):
            parse_judge_json("This is not JSON at all, just random text.")

    def test_overall_recomputed_if_wrong(self):
        """Overall should be recomputed if it doesn't match the average."""
        data = {
            "vocabulary_score": 4,
            "engagement_score": 4,
            "story_arc_score": 4,
            "moral_score": 4,
            "overall": 2.0,
            "feedback": "Test",
            "specific_fixes": [],
        }
        result = parse_judge_json(json.dumps(data))
        self.assertEqual(result["overall"], 4.0)

    def test_overall_added_if_missing(self):
        """Overall should be computed if not present."""
        data = {
            "vocabulary_score": 3,
            "engagement_score": 5,
            "story_arc_score": 4,
            "moral_score": 4,
            "feedback": "Good",
            "specific_fixes": [],
        }
        result = parse_judge_json(json.dumps(data))
        self.assertEqual(result["overall"], 4.0)

    def test_json_with_markdown_fences(self):
        """JSON wrapped in ```json ... ``` should be extracted."""
        text = '```json\n{"vocabulary_score": 5, "engagement_score": 5, "story_arc_score": 5, "moral_score": 5, "overall": 5.0, "feedback": "Perfect", "specific_fixes": []}\n```'
        result = parse_judge_json(text)
        self.assertEqual(result["overall"], 5.0)


class TestScoreDisplay(unittest.TestCase):
    """Visual output formatting for scores."""

    def test_bar_full(self):
        """Score 5 should produce all filled blocks."""
        self.assertEqual(_bar(5), "\u2588\u2588\u2588\u2588\u2588")

    def test_bar_empty(self):
        """Score 0 should produce all empty blocks."""
        self.assertEqual(_bar(0), "\u2591\u2591\u2591\u2591\u2591")

    def test_bar_partial(self):
        """Score 3 should produce 3 filled + 2 empty."""
        self.assertEqual(_bar(3), "\u2588\u2588\u2588\u2591\u2591")

    def test_bar_overflow(self):
        """Score > 5 should cap at 5 filled."""
        self.assertEqual(_bar(7), "\u2588\u2588\u2588\u2588\u2588")

    def test_bar_negative(self):
        """Negative score should produce all empty."""
        self.assertEqual(_bar(-1), "\u2591\u2591\u2591\u2591\u2591")

    def test_print_scores_pass(self):
        """Scores >= 4.0 should show pass indicator."""
        result = {"vocabulary_score": 5, "engagement_score": 4, "story_arc_score": 5, "moral_score": 4, "overall": 4.5}
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            print_scores(result, 1)
        output = mock_out.getvalue()
        self.assertIn("Round 1", output)
        self.assertIn("4.5", output)

    def test_print_scores_fail(self):
        """Scores < 4.0 should show retry indicator."""
        result = {"vocabulary_score": 2, "engagement_score": 3, "story_arc_score": 2, "moral_score": 3, "overall": 2.5}
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            print_scores(result, 2)
        output = mock_out.getvalue()
        self.assertIn("Round 2", output)
        self.assertIn("2.5", output)


class TestEnvironmentCheck(unittest.TestCase):
    """API key validation."""

    def test_missing_key_exits(self):
        """Case 6: No OPENAI_API_KEY should exit with code 1."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            with self.assertRaises(SystemExit) as ctx:
                check_api_key()
            self.assertEqual(ctx.exception.code, 1)

    def test_unset_key_exits(self):
        """Completely unset key should exit."""
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                check_api_key()
            self.assertEqual(ctx.exception.code, 1)

    def test_valid_key_passes(self):
        """Valid key should not exit."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}, clear=False):
            check_api_key()


class TestTokenTracker(unittest.TestCase):
    """Cost tracking accuracy."""

    def test_initial_state(self):
        """New tracker starts at zero."""
        t = TokenTracker()
        self.assertEqual(t.api_calls, 0)
        self.assertEqual(t.total_tokens, 0)

    def test_record_call(self):
        """Recording a call increments counters."""
        t = TokenTracker()
        t.record_call("Hello world", "Response here", 100)
        self.assertEqual(t.api_calls, 1)
        self.assertGreater(t.total_tokens, 0)

    def test_multiple_calls(self):
        """Multiple calls accumulate."""
        t = TokenTracker()
        t.record_call("prompt1", "resp1", 100)
        t.record_call("prompt2", "resp2", 100)
        self.assertEqual(t.api_calls, 2)

    def test_summary_format(self):
        """Summary string contains expected elements."""
        t = TokenTracker()
        t.record_call("x" * 400, "y" * 200, 700)
        summary = t.summary()
        self.assertIn("API calls", summary)
        self.assertIn("tokens", summary)
        self.assertIn("$", summary)


# ===========================================================================
# INTEGRATION TESTS (mocked API calls)
# ===========================================================================


class TestClassifier(unittest.TestCase):
    """Category classification with mocked API."""

    @patch("agents.call_model_with_retry")
    def test_clear_category(self, mock_call):
        """Case 8: Clear request returns correct category."""
        from agents import Classifier
        mock_call.return_value = "fantasy"
        c = Classifier()
        result = c.classify("a story about dragons and magic")
        self.assertEqual(result, "fantasy")

    @patch("agents.call_model_with_retry")
    def test_invalid_response_falls_back(self, mock_call):
        """Case 10: Invalid classifier output falls back to 'adventure'."""
        from agents import Classifier
        mock_call.return_value = "something_invalid"
        c = Classifier()
        result = c.classify("asdfghjkl")
        self.assertEqual(result, "adventure")

    @patch("agents.call_model_with_retry")
    def test_majority_vote(self, mock_call):
        """Self-consistency: majority vote wins."""
        from agents import Classifier
        mock_call.side_effect = ["animals", "adventure", "animals"]
        c = Classifier()
        result = c.classify("a cat goes on a trip")
        self.assertEqual(result, "animals")

    @patch("agents.call_model_with_retry")
    def test_all_invalid_votes(self, mock_call):
        """All invalid votes fall back to 'adventure'."""
        from agents import Classifier
        mock_call.return_value = "invalid_category"
        c = Classifier()
        result = c.classify("random text")
        self.assertEqual(result, "adventure")


class TestPromptRouter(unittest.TestCase):
    """Technique selection with mocked API."""

    @patch("agents.call_model_with_retry")
    def test_standard_selection(self, mock_call):
        """Case 11: Simple request returns standard."""
        from agents import PromptRouter
        mock_call.return_value = "standard"
        router = PromptRouter()
        result = router.select_technique("a bedtime story about stars")
        self.assertEqual(result, "standard")

    @patch("agents.call_model_with_retry")
    def test_decompose_selection(self, mock_call):
        """Case 12: Complex request returns decompose."""
        from agents import PromptRouter
        mock_call.return_value = "decompose"
        router = PromptRouter()
        result = router.select_technique("a fox, a firefly, a dark forest, finding home")
        self.assertEqual(result, "decompose")

    @patch("agents.call_model_with_retry")
    def test_self_correct_selection(self, mock_call):
        """Case 13: Quality request returns self_correct."""
        from agents import PromptRouter
        mock_call.return_value = "self_correct"
        router = PromptRouter()
        result = router.select_technique("the perfect story about friendship")
        self.assertEqual(result, "self_correct")

    @patch("agents.call_model_with_retry")
    def test_invalid_falls_back_to_decompose(self, mock_call):
        """Invalid router output falls back to decompose (best default)."""
        from agents import PromptRouter
        mock_call.return_value = "unknown_technique"
        router = PromptRouter()
        result = router.select_technique("anything")
        self.assertEqual(result, "decompose")

    @patch("agents.call_model_with_retry")
    def test_graceful_degradation_on_error(self, mock_call):
        """Router failure falls back to decompose silently."""
        from agents import PromptRouter
        mock_call.side_effect = Exception("API down")
        router = PromptRouter()
        result = router.select_technique("anything")
        self.assertEqual(result, "decompose")


class TestJudge(unittest.TestCase):
    """Evaluation pipeline with mocked API."""

    @patch("agents.call_model_with_retry")
    def test_successful_evaluation(self, mock_call):
        """Normal evaluation returns correct scores."""
        from agents import Judge
        mock_call.return_value = json.dumps({
            "vocabulary_score": 4,
            "engagement_score": 5,
            "story_arc_score": 4,
            "moral_score": 5,
            "overall": 4.5,
            "feedback": "Great!",
            "specific_fixes": [],
        })
        judge = Judge()
        result = judge.evaluate("Once upon a time...")
        self.assertEqual(result["overall"], 4.5)

    @patch("agents.call_model_with_retry")
    def test_malformed_json_retries(self, mock_call):
        """Malformed JSON on first try then retries and succeeds."""
        from agents import Judge
        good_json = json.dumps({
            "vocabulary_score": 4, "engagement_score": 4,
            "story_arc_score": 4, "moral_score": 4,
            "overall": 4.0, "feedback": "OK", "specific_fixes": [],
        })
        mock_call.side_effect = ["not json at all", good_json]
        judge = Judge()
        result = judge.evaluate("A story...")
        self.assertEqual(result["overall"], 4.0)

    @patch("agents.call_model_with_retry")
    def test_total_failure_returns_default(self, mock_call):
        """Both attempts fail so returns DEFAULT_RESULT."""
        from agents import Judge
        mock_call.return_value = "garbage garbage garbage"
        judge = Judge()
        result = judge.evaluate("A story...")
        self.assertEqual(result["overall"], 5.0)
        self.assertEqual(result["feedback"], "Could not evaluate \u2014 accepting story as-is.")

    @patch("agents.call_model_with_retry")
    def test_overall_recomputed(self, mock_call):
        """Judge recomputes overall even if model returns wrong value."""
        from agents import Judge
        mock_call.return_value = json.dumps({
            "vocabulary_score": 3, "engagement_score": 3,
            "story_arc_score": 3, "moral_score": 3,
            "overall": 5.0,
            "feedback": "Meh", "specific_fixes": ["fix"],
        })
        judge = Judge()
        result = judge.evaluate("A story...")
        self.assertEqual(result["overall"], 3.0)


class TestStoryteller(unittest.TestCase):
    """Story generation with mocked API."""

    @patch("agents.call_model_with_retry")
    def test_standard_generation(self, mock_call):
        """Standard technique generates a story."""
        from agents import Storyteller
        # Calls: router("standard") + story generation
        mock_call.side_effect = ["standard", "Once upon a time, a little bear went to sleep."]
        s = Storyteller()
        result = s.generate("a bear story", "animals")
        self.assertIn("bear", result)

    @patch("agents.call_model_with_retry")
    def test_decompose_generation(self, mock_call):
        """Decompose technique: router + plan + story."""
        from agents import Storyteller
        mock_call.side_effect = [
            "decompose",
            "1. Character: Fox\n2. Setting: Forest",
            "Once upon a time, a fox got lost in the forest...",
        ]
        s = Storyteller()
        result = s.generate("a fox story", "adventure")
        self.assertIn("fox", result)

    @patch("agents.call_model_with_retry")
    def test_self_correction_generation(self, mock_call):
        """Self-correction: router + draft + correction."""
        from agents import Storyteller
        mock_call.side_effect = [
            "self_correct",
            "Draft story about a cat.",
            "IMPROVEMENTS:\n1. Added sensory details\n2. Stronger ending\n\nREVISED STORY:\nA beautiful story about a cat with sensory details.",
        ]
        s = Storyteller()
        result = s.generate("a cat story", "animals")
        self.assertIn("sensory details", result)

    @patch("agents.call_model_with_retry")
    def test_refinement_with_feedback(self, mock_call):
        """Feedback injection uses the feedback dict (no router call)."""
        from agents import Storyteller
        mock_call.return_value = "A revised story with more action."
        s = Storyteller()
        feedback = {
            "feedback": "Needs more action",
            "specific_fixes": ["Add a chase scene", "Make the ending more exciting"],
        }
        result = s.generate("a fox story", "adventure", feedback=feedback)
        self.assertIn("revised", result)


# ===========================================================================
# RUN
# ===========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("\U0001f9ea Bedtime Story Generator \u2014 Test Suite")
    print("=" * 60)
    unittest.main(verbosity=2)
