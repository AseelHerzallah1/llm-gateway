"""Prompt pairs for semantic cache threshold experiments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptPair:
    label: str
    prompt_a: str
    prompt_b: str
    expect_hit_at_092: bool
    category: str


PROMPT_PAIRS: tuple[PromptPair, ...] = (
    PromptPair(
        label="identical",
        prompt_a="What is the capital of France?",
        prompt_b="What is the capital of France?",
        expect_hit_at_092=True,
        category="should_hit",
    ),
    PromptPair(
        label="paraphrase_capital",
        prompt_a="What is the capital of France?",
        prompt_b="Tell me the capital city of France.",
        expect_hit_at_092=False,
        category="paraphrase",
    ),
    PromptPair(
        label="paraphrase_greeting",
        prompt_a="Say hello in one word.",
        prompt_b="Reply with a single-word greeting.",
        expect_hit_at_092=False,
        category="paraphrase",
    ),
    PromptPair(
        label="diabetes_symptoms_vs_causes",
        prompt_a="What are the symptoms of diabetes?",
        prompt_b="What are the causes of diabetes?",
        expect_hit_at_092=False,
        category="should_miss",
    ),
    PromptPair(
        label="diabetes_symptoms_vs_treatment",
        prompt_a="What are the symptoms of diabetes?",
        prompt_b="How is diabetes treated?",
        expect_hit_at_092=False,
        category="should_miss",
    ),
    PromptPair(
        label="unrelated",
        prompt_a="What is the capital of France?",
        prompt_b="How do I bake sourdough bread?",
        expect_hit_at_092=False,
        category="should_miss",
    ),
)

DEFAULT_THRESHOLD = 0.92

# Measured with text-embedding-3-small (2026-07-22 experiments)
MEASURED_SIMILARITIES: dict[str, float] = {
    "identical": 1.0000,
    "paraphrase_capital": 0.8224,
    "paraphrase_greeting": 0.7230,
    "diabetes_symptoms_vs_causes": 0.5696,
    "diabetes_symptoms_vs_treatment": 0.4928,
    "unrelated": 0.0450,
}
