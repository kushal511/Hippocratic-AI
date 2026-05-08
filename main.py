"""
main.py — Entry point for the Bedtime Story Generator.

A CLI tool that generates high-quality bedtime stories for children ages 5–10
using a multi-agent pipeline with closed-loop quality control.

Usage:
    python main.py                  # Interactive mode
    python main.py --surprise       # Random story, no input needed
    python main.py --age 7          # Age-adaptive vocabulary (5-10)

Features:
    - Multi-agent pipeline: Classifier → MoodDetector → Storyteller → Judge
    - 12 prompting techniques with auto-selection + user override
    - Story title generation and moral extraction
    - Story continuation ("what happens next?")
    - Mood-adaptive tone (anxious/sad/excited/calm)
    - Age-adaptive vocabulary (--age flag)
    - Character memory within session
    - Reading time estimation
    - Token cost tracking
"""

import os
import sys
import random
import openai

"""
Before submitting the assignment, describe here in a few sentences what you would have built next if you spent 2 more hours on this project:

1. Memory Agent — A vector-DB-backed agent that stores past stories and user preferences across
   sessions, enabling personalized storytelling over time.
2. A/B Testing Framework — Empirically measure which prompting technique produces higher Judge
   scores per category, then update the PromptRouter with real data instead of heuristics.
3. Safety Classifier — A pre-filter agent that screens inputs for inappropriate content with a
   soft-reject that redirects rather than blocks.
4. Streaming Output — Word-by-word story display for a more engaging "being told a story" feel.
5. Voice Output — Text-to-speech integration so the story can be read aloud to the child.
"""

from agents import (
    Classifier,
    Storyteller,
    Judge,
    MoodDetector,
    TitleGenerator,
    MoralExtractor,
    CharacterMemory,
)
from utils import (
    check_api_key,
    validate_input,
    print_story,
    print_scores,
    show_progress,
    tracker,
)


# ===========================================================================
# CORE LLM INTERFACE
# ===========================================================================


def call_model(prompt: str, max_tokens: int = 3000, temperature: float = 0.1) -> str:
    """
    Call the OpenAI gpt-3.5-turbo model with the given prompt.

    This is the single point of contact with the OpenAI API.
    All other modules call this function via call_model_with_retry() in utils.py.

    Note:
        Model is fixed to gpt-3.5-turbo as required by the assignment.
        Do NOT change the model parameter.
    """
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content  # type: ignore


example_requests: str = "A story about a girl named Alice and her best friend Bob, who happens to be a cat."


# ===========================================================================
# SURPRISE MODE
# ===========================================================================

SURPRISE_PROMPTS: list = [
    "A tiny dragon who is afraid of fire learns to be brave",
    "A cloud named Cumulus who wants to become a rainbow",
    "Two best friends — a turtle and a hummingbird — go on a picnic",
    "A little star who falls from the sky and needs help getting home",
    "A magical library where the books come alive at night",
    "A shy octopus who wants to join the coral reef orchestra",
    "A brave mouse who delivers dreams to sleeping children",
    "A garden gnome who goes on an adventure when no one is looking",
    "A baby whale learning to sing its first song",
    "A pair of mismatched socks who go on a quest to find each other",
]


def get_surprise_prompt() -> str:
    """Select a random story prompt for --surprise mode."""
    return random.choice(SURPRISE_PROMPTS)


# ===========================================================================
# AGE-ADAPTIVE VOCABULARY
# ===========================================================================

# Age-specific vocabulary adjustments appended to the storyteller prompt
AGE_ADJUSTMENTS: dict = {
    5: "\n\nAGE ADJUSTMENT (age 5): Use only 1-2 syllable words. Sentences must be under 8 words. Use lots of repetition and rhythm. Story should be under 250 words.",
    6: "\n\nAGE ADJUSTMENT (age 6): Use mostly 1-2 syllable words. Sentences under 10 words. Simple dialogue is OK. Story should be 250-300 words.",
    7: "\n\nAGE ADJUSTMENT (age 7): Standard vocabulary for the age range. Sentences under 12 words. Story should be 300-350 words.",
    8: "\n\nAGE ADJUSTMENT (age 8): Can use slightly richer vocabulary. Sentences up to 15 words. More complex plot is OK. Story should be 300-400 words.",
    9: "\n\nAGE ADJUSTMENT (age 9): Richer vocabulary allowed (3-syllable words OK). Longer sentences fine. Can include mild suspense. Story should be 350-400 words.",
    10: "\n\nAGE ADJUSTMENT (age 10): Most varied vocabulary. Complex sentences OK. Can include more nuanced emotions and themes. Story should be 350-450 words.",
}


def parse_age_flag() -> int:
    """
    Parse the --age flag from command line arguments.

    Returns:
        Age value (5-10), or 7 as default if not specified.
    """
    if "--age" in sys.argv:
        try:
            idx = sys.argv.index("--age")
            age = int(sys.argv[idx + 1])
            if 5 <= age <= 10:
                return age
            else:
                print("  (Age must be 5-10, using default: 7)")
                return 7
        except (IndexError, ValueError):
            print("  (Invalid --age value, using default: 7)")
            return 7
    return 7  # Default age


# ===========================================================================
# MAIN PIPELINE
# ===========================================================================


def main() -> None:
    """
    Main pipeline orchestration.

    Flow:
        1. Environment check
        2. User input (or --surprise)
        3. Mood detection
        4. Classification
        5. Technique selection (auto + user override)
        6. Story generation + Judge refinement loop
        7. Title generation + moral extraction
        8. Display story
        9. Post-story options: changes / continuation / exit
        10. Session summary
    """
    # --- Step 1: Environment validation ---
    check_api_key()

    # --- Parse flags ---
    surprise_mode = "--surprise" in sys.argv
    target_age = parse_age_flag()

    print("Welcome to the Bedtime Story Generator!\n")
    if target_age != 7:
        print(f"  Age setting: {target_age} years old\n")

    # --- Step 2: Get and validate user input ---
    if surprise_mode:
        user_input = get_surprise_prompt()
        print(f"  [Surprise mode] Generating a random story...")
        print(f"  Prompt: \"{user_input}\"\n")
    else:
        while True:
            raw_input_text = input("What kind of story would you like? ")
            try:
                user_input = validate_input(raw_input_text)
                break
            except ValueError as e:
                print(f"  {e}\n")

    # --- Step 3: Mood detection ---
    show_progress("Detecting story mood...")
    mood_detector = MoodDetector()
    mood = mood_detector.detect(user_input)
    mood_adjustment = mood_detector.get_adjustment(mood)
    if mood != "neutral" and mood != "calm":
        print(f"  Detected mood: {mood} (adjusting story tone)")
    else:
        print(f"  Mood: {mood}")

    # --- Step 4: Classify the request ---
    show_progress("Classifying your story request...")
    classifier = Classifier()
    category = classifier.classify(user_input)
    print(f"  Category: {category.capitalize()}\n")

    # --- Step 5: Technique selection ---
    storyteller = Storyteller()
    judge = Judge()
    title_gen = TitleGenerator()
    moral_ext = MoralExtractor()
    character_memory = CharacterMemory()

    auto_technique = storyteller.router.select_technique(user_input)
    print(f"\n  Auto-selected technique: {auto_technique}")
    print("  Options: [1] standard  [2] decompose  [3] self_correct  [Enter] keep auto")
    technique_choice = input("  Select technique: ").strip()

    technique_map = {"1": "standard", "2": "decompose", "3": "self_correct"}
    technique_override = technique_map.get(technique_choice, auto_technique)
    print(f"  Using: {technique_override}\n")

    # --- Apply mood and age adjustments to storyteller prompts ---
    # Temporarily modify the category prompt with mood + age adjustments
    import prompts
    original_prompt = prompts.STORYTELLER_SYSTEM_PROMPTS[category]
    adjusted_prompt = original_prompt + mood_adjustment + AGE_ADJUSTMENTS.get(target_age, "")
    prompts.STORYTELLER_SYSTEM_PROMPTS[category] = adjusted_prompt

    # --- Step 6: Storyteller + Judge refinement loop ---
    best_story: str = ""
    best_score: float = 0.0
    feedback = None
    MAX_ITERATIONS: int = 2

    for iteration in range(1, MAX_ITERATIONS + 1):
        show_progress(f"Generating your story (attempt {iteration}/{MAX_ITERATIONS})...")
        story = storyteller.generate(
            user_input, category, feedback=feedback, technique_override=technique_override
        )

        show_progress("Evaluating story quality...")
        result = judge.evaluate(story)
        print_scores(result, iteration)

        if result["overall"] > best_score:
            best_score = result["overall"]
            best_story = story

        if result["overall"] >= 4.0:
            print("  Story accepted.\n")
            break
        elif iteration < MAX_ITERATIONS:
            print(f"  Refining story based on feedback...\n")
            feedback = result
        else:
            print(f"  Used best story from {MAX_ITERATIONS} attempts (score: {best_score:.1f}/5.0)\n")

    # Restore original prompt
    prompts.STORYTELLER_SYSTEM_PROMPTS[category] = original_prompt

    # --- Step 7: Title + Moral extraction ---
    show_progress("Generating title and extracting moral...")
    title = title_gen.generate(best_story)
    moral = moral_ext.extract(best_story)

    # --- Step 8: Display the final story ---
    print_story(best_story, title=title, moral=moral)

    # --- Remember characters for continuation ---
    character_memory.remember(best_story)

    # --- Step 9: Post-story options ---
    print("\nWhat would you like to do next?")
    print("  [1] Request changes (e.g. 'make it funnier', 'add a dragon')")
    print("  [2] Continue the story ('what happens next?')")
    print("  [Enter] Finish and say goodnight")
    post_choice = input("  Your choice: ").strip()

    if post_choice == "2" or post_choice.lower().startswith("what happens"):
        # Story continuation
        show_progress("Writing the next chapter...")
        continuation = character_memory.generate_continuation(category)
        cont_title = title_gen.generate(continuation)
        cont_moral = moral_ext.extract(continuation)
        print_story(continuation, title=f"{cont_title} (Part 2)", moral=cont_moral)

    elif post_choice == "1" or (post_choice and post_choice != ""):
        # User feedback / changes
        if post_choice == "1":
            user_feedback = input("  Describe your changes: ").strip()
        else:
            user_feedback = post_choice

        if user_feedback:
            if len(user_feedback) > 200:
                user_feedback = user_feedback[:200]
                print("  (Your feedback was trimmed to 200 characters)")

            custom_feedback = {
                "feedback": user_feedback,
                "specific_fixes": [user_feedback],
            }
            show_progress("Applying your changes...")
            revised_story = storyteller.generate(user_input, category, feedback=custom_feedback)
            revised_title = title_gen.generate(revised_story)
            revised_moral = moral_ext.extract(revised_story)
            print_story(revised_story, title=revised_title, moral=revised_moral)

    # --- Step 10: Farewell + session stats ---
    print("\nSweet dreams! Goodnight.\n")
    print(tracker.summary())


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    main()
