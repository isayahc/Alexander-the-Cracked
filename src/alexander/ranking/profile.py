"""User-editable interest profile: YAML loading and validation.

Profile lookup order (documented in the README):

1. ``--profile`` CLI flag, when given
2. ``profile.yaml`` at the repository root
3. ``~/.config/alexander/profile.yaml``

Every field is optional; the defaults below are the documented defaults and
live in one place (:class:`ScoringWeights`) so scoring code never hardcodes
weights.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

DEFAULT_PROFILE_FILENAME = "profile.yaml"
XDG_PROFILE_SUBPATH = Path("alexander") / DEFAULT_PROFILE_FILENAME


class Interest(BaseModel):
    """A single interest keyword with an optional weight (default 1.0)."""

    keyword: str
    weight: float = 1.0

    @field_validator("keyword")
    @classmethod
    def keyword_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("interest keyword must not be blank")
        return stripped

    @field_validator("weight")
    @classmethod
    def weight_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("interest weight must be positive")
        return value


class ScoringWeights(BaseModel):
    """Component weights — the documented defaults for the scoring function."""

    theme: float = 3.0
    deadline: float = 2.0
    prize: float = 1.5
    location: float = 1.0


class InterestProfile(BaseModel):
    """What the user cares about, expressed in YAML."""

    interests: list[Interest] = Field(default_factory=list)
    preferred_prize_min: int | None = None
    deadline_window_days: int = Field(default=30, gt=0)
    preferred_locations: list[str] = Field(default_factory=lambda: ["Online"])
    weights: ScoringWeights = Field(default_factory=ScoringWeights)

    @field_validator("preferred_locations")
    @classmethod
    def strip_locations(cls, value: list[str]) -> list[str]:
        return [entry.strip() for entry in value if entry.strip()]


def _parse_interests(raw: object) -> list[Interest]:
    """Accept interests as plain strings, dicts, or a mix of both."""
    if not isinstance(raw, list):
        raise ValueError("'interests' must be a list")
    parsed: list[Interest] = []
    for item in raw:
        if isinstance(item, str):
            parsed.append(Interest(keyword=item))
        elif isinstance(item, dict):
            parsed.append(Interest(**item))
        else:
            raise ValueError(f"unsupported interest entry: {item!r}")
    return parsed


def profile_from_mapping(data: dict[str, object]) -> InterestProfile:
    """Build a profile from an already-parsed YAML mapping."""
    data = dict(data)
    data["interests"] = _parse_interests(data.get("interests", []))
    return InterestProfile(**data)  # type: ignore[arg-type]


def load_profile(path: Path) -> InterestProfile:
    """Load and validate a profile YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return InterestProfile()
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    try:
        return profile_from_mapping(raw)
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"Invalid profile in {path}: {exc}") from exc


def resolve_profile_path(explicit: Path | None = None) -> Path | None:
    """Find the profile file to use, or None when the user has none.

    Order: explicit path, repo-root ``profile.yaml``, then the XDG location
    ``~/.config/alexander/profile.yaml``.
    """
    if explicit is not None:
        return explicit.resolve()
    repo_default = Path(DEFAULT_PROFILE_FILENAME)
    if repo_default.is_file():
        return repo_default.resolve()
    xdg_default = Path.home() / ".config" / XDG_PROFILE_SUBPATH
    if xdg_default.is_file():
        return xdg_default
    return None
