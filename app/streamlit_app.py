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

st.set_page_config(page_title="prompting-explained", layout="centered", initial_sidebar_state="collapsed")
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


def demo_files(ch: Challenge) -> list[Path]:
    return sorted(DEMO_DIR.glob(f"{ch.id}__*.json"))


ss = st.session_state
ss.setdefault("result", None)
ss.setdefault("analyses_run", 0)
ss.setdefault("error", None)

challenges = load_all()
by_id = {c.id: c for c in challenges}
config = load_config()
key_on_server = server_key()

ss.setdefault("task", challenges[0].id)
ss.setdefault("mode", "custom" if key_on_server else "example")

st.title("prompting-explained")
md('<p class="pe-subtitle">See which parts of your prompt changed the answer.</p>')

md('<p class="pe-step">1. Pick a task</p>')
cols = st.columns(len(challenges))
for col, c in zip(cols, challenges):
    with col:
        selected = ss.task == c.id
        if st.button(c.title, key=f"task_{c.id}", type="primary" if selected else "secondary", use_container_width=True):
            if not selected:
                ss.task, ss.result, ss.error = c.id, None, None
                st.rerun()

ch = by_id[ss.task]
md(f'<div class="pe-card">{esc(ch.scenario.strip())}</div>')
if ch.fixed_context:
    with st.expander("Attached automatically"):
        md(f'<div class="pe-doc">{text_html(ch.fixed_context.strip())}</div>')

md('<p class="pe-step">2. Write a prompt, or learn from an example</p>')
MODES = {"custom": "Write your own", "example": "Learn from an example"}


def keep_mode() -> None:
    """Clicking the selected option again would clear it; keep the last choice instead."""
    if ss.mode is None:
        ss.mode = ss.get("last_mode", "custom")
    ss.last_mode = ss.mode
    ss.result, ss.error = None, None


mode = st.segmented_control(
    "How do you want to start?", list(MODES), format_func=MODES.get, key="mode",
    label_visibility="collapsed", on_change=keep_mode,
) or ss.get("last_mode", "custom")


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


if mode == "example":
    files = demo_files(ch)
    examples = {p: AnalysisResult.model_validate_json(p.read_text()) for p in files}
    md('<p class="pe-muted">These prompts were analyzed ahead of time, so they open instantly.</p>')
    for path, ex in examples.items():
        shown = ss.result is not None and ss.result.user_prompt == ex.user_prompt
        if st.button(ex.user_prompt, key=f"ex_{path.stem}", type="primary" if shown else "secondary", use_container_width=True):
            ss.result, ss.error = ex, None
            st.rerun()
else:
    prompt = st.text_area("Your prompt", height=120, key=f"prompt_{ch.id}", placeholder="Write the prompt you'd give the AI.")
    capped = ss.analyses_run >= SESSION_CAP
    if not key_on_server:
        st.info("Live analysis isn't set up here (no API key). Try \"Learn from an example\" instead.")
    elif capped:
        st.info(f"You've used the {SESSION_CAP} analyses for this session. The examples still work.")
    elif st.button("Analyze", type="primary"):
        ss.error = None
        if prompt.strip():
            run_live(prompt)
        else:
            ss.error = "Write a prompt first."

if ss.error:
    st.error(ss.error)


def heatmap(res: AnalysisResult) -> str:
    max_abs = max((F.strength(res, s.id) for s in res.segments), default=0.0) or 1.0
    out = []
    for s in res.segments:
        v = {"mattered": "helped", "hurt": "hurt"}.get(F.kind(res, s.id), "no effect")
        lead = s.text[: len(s.text) - len(s.text.lstrip())]
        trail = s.text[len(s.text.rstrip()) :]
        core = text_html(s.text.strip())
        if v == "no effect":
            span = f'<span class="pe-seg noise">{core}</span>'
        else:
            alpha = 0.35 + 0.65 * F.strength(res, s.id) / max_abs
            rgb = "207,232,213" if v == "helped" else "245,211,208"
            span = f'<span class="pe-seg" style="background: rgba({rgb},{alpha:.2f})">{core}</span>'
        out.append(esc(lead) + span + text_html(trail))
    return f'<div class="pe-heat">{"".join(out)}</div>'


def what_mattered(res: AnalysisResult) -> str:
    cls = {"mattered": "helped", "hurt": "hurt"}
    return "".join(
        f'<div class="pe-item"><p class="pe-head {cls.get(kind, "none")}">{esc(head)}</p><p class="pe-why">{esc(why)}</p></div>'
        for kind, head, why in F.simple_items(res)
    )


def how_measured(res: AnalysisResult) -> None:
    with st.expander("How this was measured"):
        checks = ", ".join(r.label.lower() for r in ch.requirements)
        st.markdown(
            f"We ran your prompt {len(res.baseline_runs)} times, then removed one part at a time and ran it "
            f"{res.config.get('ablation_runs', 1)} more times. Each answer was checked automatically for: {checks}. "
            "A part mattered if removing it moved the score by more than the normal run-to-run variation "
            f"(here {F.f2(res.noise[OVERALL])} on a 0 to 1 scale), or if an AI reading the answers found they "
            "stopped doing what that part asked once it was removed."
        )
        def pct(x):
            return "n/a" if x is None else f"{round(100 * x)}%"

        judged = bool(res.follow_with)
        head = "| Part | Score with it | Without it |" + (" Did it, with | Did it, without |" if judged else "")
        rows = [head, "|---|---|---|" + ("---|---|" if judged else "")]
        for s in res.segments:
            row = (
                f"| {F.short_segment(s.text).replace('|', '/')} | {F.f2(res.baseline_mean[OVERALL])} | "
                f"{F.f2(res.ablations[s.id].mean[OVERALL])} |"
            )
            if judged:
                row += f" {pct(res.follow_with[s.id])} | {pct(res.follow_without[s.id])} |"
            rows.append(row)
        st.markdown("\n".join(rows))
        st.caption(
            "\"Did it\" is an AI's judgement of whether the answers did what that part asked. "
            "The sentences about parts that mattered were written by an AI comparing the two answers. "
            f"The rest is fixed text. This analysis used {res.calls} calls to {res.model}."
        )


res = ss.result
if res is not None:
    st.write("")
    md(heatmap(res))
    md('<p class="pe-muted">Green: it changed the answer. Red: the answer did better without it. '
       "Grey: no real difference.</p>")
    st.subheader("What mattered")
    md(what_mattered(res))
    with st.expander("See the AI's answer"):
        mono = " mono" if ch.id == "job_extraction" else ""
        md(f'<div class="pe-answer{mono}">{text_html(res.baseline_runs[0].answer)}</div>')
    how_measured(res)
    if st.button("Try again"):
        ss.result, ss.error = None, None
        st.rerun()

st.write("")
with st.expander("About this tool"):
    st.markdown(
        "This tool removes one part of your prompt at a time, reruns it, and checks whether the answer "
        "changed. Results are estimates for one AI model on these tasks, not general rules."
    )
