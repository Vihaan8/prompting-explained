"""Pydantic models shared across the engine, the UI, and the eval scripts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

OVERALL = "overall"

ROLES = (
    "role",
    "audience",
    "task",
    "context",
    "constraint",
    "format",
    "tone",
    "example",
    "politeness_filler",
    "other",
)


class Requirement(BaseModel):
    """One code-checkable requirement of a challenge."""

    id: str
    label: str
    short: str = ""  # noun phrase for findings: "made the answer worse at {short}"
    scorer: str
    params: dict[str, Any] = Field(default_factory=dict)
    gate: bool = False  # if true, the overall score is multiplied by this score instead of averaged

    @field_validator("id")
    @classmethod
    def _not_overall(cls, v: str) -> str:
        if v == OVERALL:
            raise ValueError(f"requirement id '{OVERALL}' is reserved")
        return v

    @model_validator(mode="after")
    def _default_short(self) -> "Requirement":
        if not self.short:
            self.short = self.id.replace("_", " ")
        return self


class Challenge(BaseModel):
    """A task the user writes a prompt for, loaded from challenges/*.yaml."""

    id: str
    title: str
    level: int
    category: str = "Other"  # groups tasks in the task menu
    subtitle: str = ""  # what the task practices, shown under its title
    scenario: str
    fixed_context: str | None = None
    requirements: list[Requirement]
    reference_prompt: str

    @model_validator(mode="after")
    def _unique_requirement_ids(self) -> "Challenge":
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate requirement ids in {self.id}: {ids}")
        return self

    @property
    def targets(self) -> list[str]:
        """Attribution targets: 'overall' followed by each requirement id."""
        return [OVERALL] + [r.id for r in self.requirements]

    def requirement(self, req_id: str) -> Requirement:
        """Look up a requirement by id."""
        return next(r for r in self.requirements if r.id == req_id)


class Segment(BaseModel):
    """A contiguous piece of the user's prompt. [start, end) indexes the prompt text."""

    id: int
    text: str
    role: str
    start: int
    end: int

    @property
    def display(self) -> str:
        """The segment text without surrounding whitespace."""
        return self.text.strip()


class LLMResponse(BaseModel):
    """One model call's output and usage."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stop_reason: str | None = None


class RunResult(BaseModel):
    """One answer and its scores. `scores` holds each requirement id plus 'overall'."""

    answer: str
    scores: dict[str, float]
    stop_reason: str | None = None


class Ablation(BaseModel):
    """Runs of the prompt with one segment removed."""

    segment_id: int
    prompt: str
    runs: list[RunResult]
    mean: dict[str, float]


class AnalysisResult(BaseModel):
    """Everything one analysis computed. Saved as JSON for demo mode and the eval."""

    challenge_id: str
    user_prompt: str
    final_prompt: str
    segments: list[Segment]
    segmentation_method: str  # "llm" | "fallback" | "given"
    targets: list[str]

    baseline_runs: list[RunResult]
    baseline_mean: dict[str, float]
    baseline_std: dict[str, float]
    noise: dict[str, float]
    pooled_std: dict[str, float] = Field(default_factory=dict)  # spread over all repeated runs (eval reporting)
    # part_noise[segment_id][target]: the floor that part's effect is compared with (see diff_noise)
    part_noise: list[dict[str, float]] = Field(default_factory=list)

    ablations: list[Ablation]
    # attribution[segment_id][target] = baseline_mean[target] - ablated_mean[target]
    attribution: list[dict[str, float]]
    within_noise: list[dict[str, bool]]

    explanations: dict[int, str] = Field(default_factory=dict)

    # Per-part check (core/judge.py). Ratings are 1 / 0.5 / 0, or None for n/a.
    judge_baseline: list[list[float | None] | None] = Field(default_factory=list)
    judge_ablation: list[list[list[float | None] | None]] = Field(default_factory=list)
    follow_with: list[float | None] = Field(default_factory=list)  # did answers with the part do it
    follow_without: list[float | None] = Field(default_factory=list)  # did answers without it still do it

    call_counts: dict[str, int] = Field(default_factory=dict)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
