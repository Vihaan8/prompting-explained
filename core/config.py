"""Load and validate config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


class Prices(BaseModel):
    """USD per million tokens, for cost estimates only."""

    input: float = 0.0
    output: float = 0.0


class Config(BaseModel):
    """Every tunable the engine uses. Defaults mirror config.yaml."""

    provider: Literal["anthropic"] = "anthropic"
    model: str = "claude-haiku-5-5"
    temperature: float | None = None
    thinking: Literal["disabled", "adaptive"] = "disabled"
    effort: Literal["low", "medium", "high"] | None = "low"
    max_tokens: int = 800
    segment_max_tokens: int = 2000
    explain_max_tokens: int = 120
    judge_parts: bool = True
    judge_max_tokens: int = 600

    baseline_runs: int = Field(3, ge=1)
    ablation_runs: int = Field(2, ge=1)
    max_segments: int = Field(10, ge=1)
    noise_floor_k: float = 2.0
    min_noise_floor: float = 0.05
    ablation_mode: Literal["delete", "filler"] = "delete"
    max_concurrency: int = Field(8, ge=1)
    max_calls_per_analysis: int = Field(60, ge=1)
    explain_top_n: int = 3

    price_per_mtok: Prices = Prices()

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate the dollar cost of a token count at the configured prices."""
        return (
            input_tokens * self.price_per_mtok.input + output_tokens * self.price_per_mtok.output
        ) / 1_000_000


def load_config(path: Path | str = CONFIG_PATH, **overrides) -> Config:
    """Read config.yaml and apply keyword overrides (used by tests and scripts)."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    data.update(overrides)
    return Config(**data)
