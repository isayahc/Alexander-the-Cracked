"""Pure prompt and README rendering checks."""

from alexander.builder.prompts import render_attempt_prompt, render_fallback_readme


def test_prompt_carries_brief_and_attempt_number(brief) -> None:
    prompt = render_attempt_prompt(brief, attempt=2, max_attempts=5)
    assert brief.event_name in prompt
    assert brief.description in prompt
    assert "attempt 2 of 5" in prompt
    assert "Feedback from the previous attempt" not in prompt


def test_prompt_carries_failure_notes(brief) -> None:
    prompt = render_attempt_prompt(
        brief, attempt=3, max_attempts=5, failure_notes="tests failed: 1 failed"
    )
    assert "tests failed: 1 failed" in prompt


def test_prompt_lists_optional_fields_when_missing() -> None:
    from alexander.builder import HackathonBrief

    prompt = render_attempt_prompt(
        HackathonBrief(event_name="Bare", description="Do a thing"), attempt=1, max_attempts=1
    )
    assert "Deadline: not stated" in prompt
    assert "Prize: not stated" in prompt
    assert "Themes: none listed" in prompt


def test_fallback_readme_contains_pitch_and_summary(brief) -> None:
    readme = render_fallback_readme(brief, "tests passed: 1 passed in 0.01s")
    assert brief.event_name in readme
    assert brief.description in readme
    assert "tests passed: 1 passed in 0.01s" in readme
    assert "Pitch" in readme
