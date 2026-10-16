"""prompting-explained: see which parts of your prompt changed the answer.

Run with:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import asyncio
import html
import math
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import findings as F  # noqa: E402
from core.attribution import analyze  # noqa: E402
from core.challenges import load_all  # noqa: E402
from core.config import load_config  # noqa: E402
from core.explain import make_explainer  # noqa: E402
from core.llm import BudgetExceeded, make_llm  # noqa: E402
from core.types import OVERALL, AnalysisResult, Challenge  # noqa: E402

DEMO_DIR = ROOT / "demo_examples"
SESSION_CAP = 10  # analyses per session on the server's key
CATEGORY_ORDER = ["Explain", "Write", "Extract", "Responsible AI", "Other"]

st.set_page_config(page_title="prompting-explained", layout="wide", initial_sidebar_state="collapsed")
st.markdown(f"<style>{(ROOT / 'app' / 'styles.css').read_text()}</style>", unsafe_allow_html=True)


def esc(text: str) -> str:
    return html.escape(text)


def text_html(text: str) -> str:
    """Escaped text with newlines as <br>, so blank lines can't end the HTML block early."""
    return esc(text).replace("\r", "").replace("\n", "<br>")


def md(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def server_key() -> str | None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:  # no secrets file
        return None


def samples_for(ch: Challenge) -> list[AnalysisResult]:
    return [AnalysisResult.model_validate_json(p.read_text()) for p in sorted(DEMO_DIR.glob(f"{ch.id}__*.json"))]


ss = st.session_state
challenges = load_all()
by_id = {c.id: c for c in challenges}
config = load_config()
key_on_server = server_key()

ss.setdefault("task", challenges[0].id)
ss.setdefault("result", None)
ss.setdefault("analyses_run", 0)
ss.setdefault("error", None)
ss.setdefault("mode", "custom" if key_on_server else "sample")
ss.setdefault("last_mode", ss.mode)


def pick_task(task_id: str) -> None:
    ss.task, ss.result, ss.error = task_id, None, None
    ss.pop(f"sample_{task_id}", None)
    ss.task_menu = False  # close the menu after a pick


def keep_mode() -> None:
    """Clicking the selected option again would clear it; keep the last choice instead."""
    if ss.mode is None:
        ss.mode = ss.last_mode
    ss.last_mode = ss.mode
    ss.result, ss.error = None, None
    ss.pop(f"sample_{ss.task}", None)


ch = by_id[ss.task]


# Header: name, task menu, about

head_name, head_menu, head_about = st.columns([1.2, 1.6, 0.5], vertical_alignment="center")
with head_name:
    md('<p class="pe-brand">prompting-explained</p><p class="pe-tagline">See which parts of your prompt changed the answer.</p>')
with head_menu:
    with st.popover(f"Task: {ch.title}", use_container_width=True, key="task_menu", on_change="rerun"):
        groups: dict[str, list[Challenge]] = {}
        for c in challenges:
            groups.setdefault(c.category, []).append(c)
        for cat in sorted(groups, key=lambda g: CATEGORY_ORDER.index(g) if g in CATEGORY_ORDER else len(CATEGORY_ORDER)):
            md(f'<p class="pe-cat">{esc(cat.upper())}</p>')
            for c in groups[cat]:
                label = f"{c.title} · {c.subtitle} · Level {c.level}" if c.subtitle else c.title
                st.button(
                    label, key=f"task_{c.id}", on_click=pick_task, args=(c.id,), use_container_width=True,
                    type="primary" if c.id == ch.id else "secondary",
                )
with head_about:
    with st.popover("About", use_container_width=True):
        st.markdown(
            "This tool removes one part of your prompt at a time, reruns it, and checks whether the answer "
            "changed. Results are estimates for one AI model on these tasks, not general rules. "
            "Open the How it works tab after an analysis for the details."
        )
md('<div class="pe-rule"></div>')


def run_live(prompt: str) -> None:
    bar = st.progress(0.0, text="Splitting your prompt into parts…")
    seen, totals = {"baseline": 0, "ablation": 0}, {"baseline": config.baseline_runs, "ablation": 0}

    def progress(stage: str, done: int, total: int) -> None:
        if stage == "segment":
            bar.progress(0.05, text="Splitting your prompt into parts…")
        elif stage == "judge":
            bar.progress(0.9, text="Checking what each part did…")
        elif stage == "explain":
            bar.progress(0.95, text="Comparing answers…")
        else:
            seen[stage], totals[stage] = done, total
            frac = 0.1 + 0.85 * sum(seen.values()) / max(1, sum(totals.values()))
            if stage == "baseline":
                text = f"Running your prompt ({done} of {total})…"
            else:
                text = f"Testing part {math.ceil(done / config.ablation_runs)} of {total // config.ablation_runs}…"
            bar.progress(min(frac, 0.95), text=text)

    try:
        async def go():
            llm = make_llm(config, api_key=key_on_server)
            try:
                return await analyze(ch, prompt, llm, config, explainer=make_explainer(config), progress=progress)
            finally:
                await llm.aclose()

        result = asyncio.run(go())
    except BudgetExceeded:
        ss.error = "This prompt has too many parts to test. Try a shorter one."
        return
    except Exception as e:  # API and network errors
        ss.error = f"Something went wrong calling the model ({type(e).__name__}). Try again in a moment."
        return
    finally:
        bar.empty()
    ss.result = result
    ss.analyses_run += 1
    st.rerun()


left, right = st.columns([1, 1.65], gap="large")

# Left: the task and the prompt

shown: AnalysisResult | None = None
with left:
    md(f'<p class="pe-label">Task {challenges.index(ch) + 1} · {esc(ch.category)} · Level {ch.level}</p>')
    md(f'<h1 class="pe-title">{esc(ch.title)}</h1>')
    md(f'<p class="pe-scenario">{esc(ch.scenario.strip())}</p>')
    if ch.fixed_context:
        with st.expander("Attached automatically"):
            md(f'<div class="pe-doc">{text_html(ch.fixed_context.strip())}</div>')

    MODES = {"custom": "Write my own", "sample": "Samples"}
    mode = st.segmented_control(
        "Start with", list(MODES), format_func=MODES.get, key="mode", on_change=keep_mode, label_visibility="collapsed"
    ) or ss.last_mode

    if mode == "sample":
        samples = samples_for(ch)
        pick = st.radio(
            "Pick a sample prompt",
            list(range(len(samples))),
            format_func=lambda i: f"Sample {i + 1}: {samples[i].user_prompt}",
            index=None,
            key=f"sample_{ch.id}",
            help="These were analyzed ahead of time, so they open instantly.",
        )
        shown = samples[pick] if pick is not None else None
    else:
        prompt = st.text_area("Your prompt", height=150, key=f"prompt_{ch.id}", placeholder="Write the prompt you'd give the AI.")
        if not key_on_server:
            st.info("Live analysis isn't set up here (no API key). Switch to Samples to see saved results.")
        elif ss.analyses_run >= SESSION_CAP:
            st.info(f"You've used the {SESSION_CAP} analyses for this session. The samples still work.")
        elif st.button("Analyze prompt", type="primary"):
            ss.error = None
            if prompt.strip():
                run_live(prompt)
            else:
                ss.error = "Write a prompt first."
        shown = ss.result
    if ss.error:
        st.error(ss.error)


# Right: results and how it works

BADGE = {
    "mattered": ("Mattered", "good"),
    "followed": ("AI followed it", "followed"),
    "hurt": ("Worked against you", "bad"),
    "ignored": ("Ignored", "neutral"),
    "unclear": ("Not clear", "neutral"),
    "anyway": ("Didn't matter", "neutral"),
    "quiet": ("Didn't matter", "neutral"),
}


def heatmap(res: AnalysisResult) -> str:
    max_abs = max((F.strength(res, s.id) for s in res.segments), default=0.0) or 1.0
    out = []
    for s in res.segments:
        k = F.kind(res, s.id)
        lead = s.text[: len(s.text) - len(s.text.lstrip())]
        trail = s.text[len(s.text.rstrip()) :]
        core = text_html(s.text.strip())
        if k in ("mattered", "hurt", "followed"):
            alpha = 0.35 + 0.65 * F.strength(res, s.id) / max_abs
            rgb = {"mattered": "207,232,213", "hurt": "245,211,208", "followed": "215,230,243"}[k]
            span = f'<span class="pe-seg" style="background: rgba({rgb},{alpha:.2f})">{core}</span>'
        else:
            span = f'<span class="pe-seg noise">{core}</span>'
        out.append(esc(lead) + span + text_html(trail))
    return f'<div class="pe-heat">{"".join(out)}</div>'


def cards(res: AnalysisResult) -> str:
    rows = []
    for kind, head, why in F.simple_items(res):
        label, tone = BADGE[kind]
        if head.endswith(" most"):
            label, head = "Mattered most", head[: -len(" most")]
        for tail in (" mattered", ": the AI followed it", " worked against you", " was ignored", " didn't matter here", " didn't matter", ": not clear"):
            if head.endswith(tail):
                head = head[: -len(tail)]
                break
        rows.append(
            f'<article class="pe-card-item"><span class="pe-badge {tone}">{esc(label)}</span>'
            f'<p class="pe-card-head">{esc(head)}</p><p class="pe-card-why">{esc(why)}</p></article>'
        )
    return f'<div class="pe-grid">{"".join(rows)}</div>'


def how_it_works(res: AnalysisResult) -> None:
    runs = ", ".join(F.f2(r.scores[OVERALL]) for r in res.baseline_runs)
    checks = "; ".join(r.label for r in ch.requirements)
    per_part = res.config.get("ablation_runs", 1)
    steps = [
        ("Split into parts", f"One AI call split your prompt into {len(res.segments)} parts and tagged each one (task, audience, format, and so on)."),
        ("Measure the full prompt", f"Your prompt ran {len(res.baseline_runs)} times. Code scored each answer from 0 to 1 on these checks: {checks}. Scores: {runs}."),
        ("Remove one part at a time", f"Each shortened prompt ran {per_part} more times. A part's effect is the score with it minus the score without it."),
        ("Check each part directly", "An AI read every answer and rated whether it did what each part asked. That catches things the code checks can't see."),
        ("Leave out the noise", "Answers vary from run to run. Each part's effect is compared with how much its own runs and your prompt's runs varied (two standard errors, at least 0.05). Smaller effects stay grey instead of being claimed."),
    ]
    md('<p class="pe-muted">The method is occlusion, also called leave-one-out attribution: remove one part, rerun, compare.</p>')
    md('<ol class="pe-steps">' + "".join(
        f'<li><span class="pe-num">{i:02d}</span><div><p class="pe-step-title">{esc(t)}</p><p class="pe-step-body">{esc(b)}</p></div></li>'
        for i, (t, b) in enumerate(steps, 1)
    ) + "</ol>")

    def pct(x):
        return "n/a" if x is None else f"{round(100 * x)}%"

    judged = bool(res.follow_with)
    rows = []
    for s in res.segments:
        cells = [esc(F.short_segment(s.text)), F.f2(res.baseline_mean[OVERALL]), F.f2(res.ablations[s.id].mean[OVERALL]),
                 F.f2(F.part_floor(res, s.id, OVERALL))]
        if judged:
            cells.append(f"{pct(res.follow_with[s.id])} / {pct(res.follow_without[s.id])}")
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    head = "<th>Part</th><th>Score with it</th><th>Without it</th><th>Noise floor</th>" + ("<th>Did it, with / without</th>" if judged else "")
    md(f'<div class="pe-table"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    check_rows = "".join(
        f"<tr><td>{esc(r.label)}</td><td>{F.f2(res.baseline_mean[r.id])}</td>"
        f"<td>{'passed' if res.baseline_mean[r.id] >= 0.999 else 'missed'}</td></tr>"
        for r in ch.requirements
    )
    md('<p class="pe-step-title" style="margin-top:18px !important">The checks, for your full prompt</p>')
    md(f'<div class="pe-table"><table><thead><tr><th>Check</th><th>Mean score</th><th>Result</th></tr></thead><tbody>{check_rows}</tbody></table></div>')
    md(
        f'<p class="pe-small">{res.calls} calls to {esc(res.model)}. "Did it" is an AI\'s judgement of whether the answers did what '
        "that part asked. The sentences about parts that mattered were written by an AI comparing the two answers; "
        "everything else is fixed text.</p>"
    )


with right:
    tab_results, tab_how = st.tabs(["Results", "How it works"])
    with tab_results:
        if shown is None:
            md('<div class="pe-empty">Your results will show up here. Write a prompt and analyze it, or pick a sample.</div>')
        else:
            md(f'<p class="pe-summary">{esc(F.summary_line(shown))}</p>')
            md(heatmap(shown))
            md(
                '<p class="pe-legend"><span class="it"><span class="sw good"></span>Made the answer better</span>'
                '<span class="it"><span class="sw followed"></span>AI followed it, score unchanged</span>'
                '<span class="it"><span class="sw bad"></span>Answer was better without it</span>'
                '<span class="it"><span class="sw neutral"></span>No real difference</span></p>'
            )
            md(cards(shown))
            with st.expander("See the AI's answer"):
                mono = " mono" if ch.id == "job_extraction" else ""
                md(f'<div class="pe-answer{mono}">{text_html(shown.baseline_runs[0].answer)}</div>')
    with tab_how:
        if shown is None:
            md('<div class="pe-empty">After an analysis, this tab shows exactly what ran and the numbers behind each color.</div>')
        else:
            how_it_works(shown)
