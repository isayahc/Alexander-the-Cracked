"""Tests for profile loading and validation."""

from pathlib import Path

import pytest

from alexander.ranking import InterestProfile, load_profile, resolve_profile_path


def write_profile(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_empty_profile_uses_documented_defaults(tmp_path: Path) -> None:
    profile = load_profile(write_profile(tmp_path, ""))
    assert profile.interests == []
    assert profile.preferred_prize_min is None
    assert profile.deadline_window_days == 30
    assert profile.preferred_locations == ["Online"]
    assert profile.weights.theme == 3.0
    assert profile.weights.deadline == 2.0
    assert profile.weights.prize == 1.5
    assert profile.weights.location == 1.0


def test_plain_string_interests_get_default_weight(tmp_path: Path) -> None:
    profile = load_profile(write_profile(tmp_path, "interests:\n  - ai\n  - web\n"))
    assert [(i.keyword, i.weight) for i in profile.interests] == [("ai", 1.0), ("web", 1.0)]


def test_weighted_dict_interests_are_kept(tmp_path: Path) -> None:
    content = "interests:\n  - keyword: climate\n    weight: 2.5\n"
    profile = load_profile(write_profile(tmp_path, content))
    assert [(i.keyword, i.weight) for i in profile.interests] == [("climate", 2.5)]


def test_mixed_interest_forms_load(tmp_path: Path) -> None:
    content = "interests:\n  - ai\n  - keyword: climate\n    weight: 2.0\n"
    profile = load_profile(write_profile(tmp_path, content))
    assert [i.keyword for i in profile.interests] == ["ai", "climate"]


def test_blank_keyword_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="blank"):
        load_profile(write_profile(tmp_path, "interests:\n  - '   '\n"))


def test_non_positive_weight_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        load_profile(write_profile(tmp_path, "interests:\n  - keyword: ai\n    weight: 0\n"))


def test_non_mapping_profile_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mapping"):
        load_profile(write_profile(tmp_path, "- just\n- a\n- list\n"))


def test_defaults_instantiate_without_yaml() -> None:
    assert InterestProfile() is not None


def test_resolve_prefers_explicit_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no profile.yaml in cwd
    explicit = tmp_path / "custom.yaml"
    explicit.write_text("interests: []", encoding="utf-8")
    assert resolve_profile_path(explicit) == explicit


def test_resolve_falls_back_to_repo_root_then_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_profile_path() is None
    (tmp_path / "profile.yaml").write_text("interests: []", encoding="utf-8")
    assert resolve_profile_path() == tmp_path / "profile.yaml"
