"""Redraw the poster's "which kinds of phrases mattered" chart from results/roles.csv.

    python scripts/poster_chart.py

Writes docs/poster/q3_phrase_kinds.png. Run scripts/run_eval.py --stage report first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ROOT  # noqa: E402

OUT = ROOT / "docs" / "poster" / "q3_phrase_kinds.png"
SAGE, GREY, INK = "#2F6340", "#B5B0A8", "#2B2A28"

# Roles shown on the poster, in plain words. "other" and "example" are left out (too few parts).
LABELS = {
    "format": 'Format  ("use 3 bullet points")',
    "task": 'The task  ("explain inflation")',
    "audience": 'Audience  ("for a 10-year-old")',
    "context": "Background details",
    "constraint": 'Rules and limits  ("under 60 words")',
    "politeness_filler": 'Politeness  ("please", "thanks")',
    "tone": 'Tone  ("be friendly")',
}
MUTED_ROLES = {"politeness_filler", "tone"}


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    roles = pd.read_csv(ROOT / "results" / "roles.csv")
    roles = roles[roles.role.isin(LABELS)].sort_values("mean_abs", ascending=False)

    plt.rcParams.update({"font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"]})
    fig, ax = plt.subplots(figsize=(10.0, 6.6), dpi=200)
    ys = range(len(roles))
    colors = [GREY if r in MUTED_ROLES else SAGE for r in roles.role]
    ax.barh(list(ys), roles.mean_abs, color=colors, height=0.62)
    for y, v in zip(ys, roles.mean_abs):
        ax.text(v + 0.004, y, f"{v:.2f}", va="center", fontsize=24, color=INK)
    ax.set_yticks(list(ys), [LABELS[r] for r in roles.role], fontsize=21, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, roles.mean_abs.max() * 1.18)
    ax.set_xticks([])
    ax.tick_params(left=False)
    for side in ax.spines.values():
        side.set_visible(False)
    fig.suptitle("How much the score (out of 1) moved when this kind of phrase was removed", fontsize=20, color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT, facecolor="white")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
