"""Load and validate challenge YAML files."""

from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from .config import ROOT
from .scorers import SCORERS
from .types import Challenge

CHALLENGE_DIR = ROOT / "challenges"


def validate(ch: Challenge) -> Challenge:
    """Check that every requirement names a registered scorer with matching params."""
    for req in ch.requirements:
        if req.scorer not in SCORERS:
            raise ValueError(f"{ch.id}/{req.id}: unknown scorer '{req.scorer}'")
        try:
            inspect.signature(SCORERS[req.scorer]).bind("", **req.params)
        except TypeError as e:
            raise ValueError(f"{ch.id}/{req.id}: bad params for {req.scorer}: {e}") from e
    return ch


def load_challenge_file(path: Path | str) -> Challenge:
    """Load one challenge YAML."""
    data = yaml.safe_load(Path(path).read_text())
    return validate(Challenge(**data))


def challenge_paths(directory: Path = CHALLENGE_DIR) -> list[Path]:
    """Challenge files sorted by their numeric prefix."""
    return sorted(directory.glob("*.yaml"))


def load_all(directory: Path = CHALLENGE_DIR) -> list[Challenge]:
    """Load every challenge in order."""
    return [load_challenge_file(p) for p in challenge_paths(directory)]


def get_challenge(key: str, directory: Path = CHALLENGE_DIR) -> Challenge:
    """Find a challenge by id ('explain_to_kid'), file prefix ('01'), or file stem."""
    for p in challenge_paths(directory):
        ch = load_challenge_file(p)
        if key in (ch.id, p.stem) or p.stem.startswith(f"{key}_") or p.stem.lstrip("0").startswith(f"{key}_"):
            return ch
    raise KeyError(f"no challenge matches '{key}'")
