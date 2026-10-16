# prompting-explained

A small web app that shows which parts of your prompt actually changed an AI's answer.

You pick a task (explain inflation to a 10-year-old, push back on a late fee, turn a messy job posting into JSON), write a prompt, and the app takes it apart. It runs your prompt a few times, then runs it again with one piece removed at a time, and tells you which pieces made a difference and which ones the AI would have handled anyway. "Please" and "thanks" almost never matter. "Use 3 bullet points" almost always does. Sometimes the attached email does all the work and nothing you wrote matters much, which is useful to know too.

![Picking a task and an example prompt, then the prompt with highlighted parts and what mattered](docs/screenshot.jpg)

I built this for an explainable AI course. The question I wanted to answer:

> Can perturbation-based attributions over prompt segments give everyday users faithful and stable explanations of how their wording shapes an LLM's output?

Short version of the answer, for one model (Claude Haiku 5.5) on three tasks: mostly yes for the big effects, and no for small ones. The top-ranked parts really are the ones that matter (removing them hurts about 75% more than removing random parts). Rerunning the same analysis gives the same top part 83% of the time. Small effects get lost in the model's run-to-run randomness, so the app says so instead of guessing.

## How it works

1. **Split the prompt into parts.** One model call splits the prompt into short phrases and labels each one (task, audience, format, constraint, politeness, and so on). The code then maps every part back onto the exact characters of the prompt, so removing a part removes exactly that text.
2. **Run the full prompt 3 times.** Each answer is scored by code against the task's checks. For the kid task those are: actually explains prices, 3 bullet points, 60 words or fewer, reading grade 5 or below. The spread across the 3 runs sets a noise floor. Changes smaller than that aren't reported as real.
3. **Remove one part at a time and run each version twice.** The drop in score is that part's effect. This is occlusion, or leave-one-out.
4. **Check each part directly.** A second model call reads every answer and rates whether it does what each part of the prompt asked: yes, partly, no, or nothing to act on. If answers do something with the part and stop doing it without the part, that part mattered. If they do it either way, the AI did it anyway.
5. **Explain it in plain words.** Parts that mattered get one sentence written by the model comparing the two answers. Everything else is fixed text picked by the numbers, so the app never invents a number.

The colours are simple. Green means the part changed the answer. Red means the answer did better without it. Grey means no real difference. "How this was measured" at the bottom has the actual scores for anyone who wants to check.

Any document that comes with a task (the landlord's email, the job posting) is attached after your prompt and never removed.

## The XAI ideas behind it

| Idea | Where it comes from | How it shows up here |
|---|---|---|
| Occlusion | Zeiler and Fergus (2014); the course's attribution chapter | Remove a prompt part, rerun, measure the change |
| Perturbation explanations for text | LIME (Ribeiro et al., 2016) masks words and fits a local model | Same black-box idea, but with phrases instead of single words and no surrogate model |
| Shapley values / SHAP | Lundberg and Lee (2017) | Not used, on purpose. One part at a time is cheap and easy to explain, but it misses interactions. That is exactly why two parts that say the same thing can both show as grey |
| Target-specific attribution | Class-specific saliency (Simonyan et al., 2014) | Each check gets its own attribution, so "under 60 words" can help length and do nothing for reading level |
| Contrastive and counterfactual explanation | The course's example-based explanations chapter | "With this part / without it" is a minimal counterfactual: the smallest edit to your prompt and what changed |
| Faithfulness by deletion | Petsiuk et al. (2018); DeYoung et al. (2020) | Remove the top-ranked parts together with fresh model calls and compare against random parts |
| Stability | Alvarez-Melis and Jaakkola (2018) | Rerun whole analyses and check whether the verdicts agree |
| Generated rationales are not evidence | Turpin et al. (2023); the course's LLM prompting section | The model-written "why" sentence is labeled as a description, never as the measurement |

## Results

Everything below comes from `results/summary.md`, produced by `scripts/run_eval.py`. The model was `claude-haiku-5-5`, with thinking off and effort low. Each analysis used 3 baseline runs and 2 runs per removed part. The prompts are 90 synthetic ones: 3 tasks × novice, average, and expert users, 10 each, written by an LLM. Expert prompts scored higher than novice ones on all three tasks (kid task 0.94 vs 0.36, landlord 1.00 vs 0.79, JSON 0.84 vs 0.06), so the synthetic users behave the way you'd hope.

**Faithfulness.** For the 30 prompts with at least 4 parts, I removed the 2 top-ranked parts together and compared that with removing 2 random parts, using new model calls each time. The top-2 removal dropped the score by 0.48 on average, against 0.27 for random parts. Top-2 hurt more in 24 of 30 prompts (one-sided Wilcoxon p = 0.0002). With 3 parts removed there was no difference (0.49 vs 0.51). Half of these prompts only have 4 parts, so 3 random parts out of 4 always overlap heavily with the top 3. That is a weak test, not evidence against the method.

![Drop in score after removing the top-k parts vs k random parts](results/faithfulness.png)

**Stability.** I reanalyzed 30 prompts from scratch, keeping the same parts.
- The ranking of parts correlated well between the two runs: median Spearman 1.00, mean 0.85, over the 17 prompts with enough parts to rank.
- The top part was the same 83% of the time.
- The full verdict (mattered / didn't / ignored) matched for 73% of parts.
- Splitting the same prompt 3 times gave identical parts 83% of the time.

**What kinds of parts matter.** Grouped by the role the splitter assigned:
- Format instructions changed the score the most: mean effect 0.27, above the noise floor 88% of the time.
- Task instructions came close behind, at 0.26.
- Politeness (0.07) and tone (0.06) changed it the least.
- On the landlord task, most parts (57 of 97) were things the AI did anyway, because the attached email and lease already say everything.

![Mean effect of each kind of prompt part](results/roles.png)

**Does it match human intuition?** Before running anything, I wrote down what I expected for 71 parts across 24 prompts (`results/expectations.yaml`). The tool agreed with me on 59 of them (83%, Cohen's kappa 0.71). When we disagreed, I was usually the one who was wrong: the AI fills in more than I expected. It writes an email even without "write a reply", and keeps replies short without being told. Two disagreements were real mistakes by the tool:
- The judge model missed that an answer was wrapped in a code block.
- An instruction to add a summary sentence after the JSON showed as green. It did change the answer, but for the worse, and the checks couldn't tell. `results/expectations_report.md` lists every disagreement.

## Things that went wrong along the way

These shaped the design, so they're worth writing down.

- **The checks rewarded non-answers.** With "explain inflation" removed, the AI asked "what would you like me to explain?" That reply is short and simple, so it passed the length and reading checks and scored better than a real answer. The tool concluded the task instruction didn't matter. I added a "did it actually do the task" check that zeroes the score for questions back, and for advice when an email was asked for. This affected about 11% of answers.
- **One run per removed part made things up.** With a single run, "Thanks so much!" looked like it helped reading level. With two runs it fell back within noise.
- **Vague prompts are noisy.** Short prompts get very different answers from run to run, which hides real effects. Instead of saying "didn't matter" in that case, the app now says it can't tell.
- **The score alone was too narrow.** Code checks can see length and keywords. They can't see whether the reply still says "I paid on time". The per-part check fills that gap.
- **The model never invented a salary.** The JSON task was meant to show hallucination. Even with a $2,000 sign-on bonus in the posting as bait, Haiku 5.5 put `null` for salary every time. That's a good result for the model and a null result for the demo, and I've reported it as one.

## Running it

Python 3.11 or newer (I used 3.12).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # add your ANTHROPIC_API_KEY
.venv/bin/streamlit run app/streamlit_app.py
```

Without a key, pick "Learn from an example" under any task to open one of six saved analyses. One live analysis is around 15 to 40 calls to Haiku, a fraction of a cent.

Tests use a fake model and make no API calls:

```bash
.venv/bin/pytest
```

To deploy on Streamlit Community Cloud, point it at `app/streamlit_app.py` and add `ANTHROPIC_API_KEY` to the app's secrets. Each browser session gets 10 analyses on the shared key.

## Reproducing the evaluation

```bash
.venv/bin/python scripts/verify_references.py      # each task's reference prompt must pass 5/5
.venv/bin/python scripts/generate_attempts.py      # 90 synthetic prompts
.venv/bin/python scripts/run_eval.py               # analyses, deletion test, reruns, per-part check, report
.venv/bin/python scripts/validate_expectations.py  # compare against hand-written expectations
.venv/bin/python scripts/run_eval.py --stage report  # redraw plots from saved results, no API calls
```

All settings live in `config.yaml`. The full evaluation cost about $0.50 in API calls. Every model output is saved under `results/`, so the numbers can be checked or rescored without rerunning anything.

## Limitations

- Results are for one model and version, on three tasks. Other models will behave differently.
- Removing one part at a time misses parts that only matter together, or parts that back each other up.
- A prompt with a piece cut out can read strangely, and that alone can change the answer.
- The splitting, the per-part check, and the "why" sentences all come from a model, and models make mistakes (see the code block miss above).
- The noise floor comes from only 3 runs, so it is itself noisy.
- The 90 eval prompts were written by an LLM pretending to be users. Real users are messier.
- People may trust a coloured heatmap more than they should. The grey and "can't tell" verdicts help, but they don't remove that risk.

## Adding a task

Drop a YAML file in `challenges/`:

```yaml
id: my_task
title: "Short title"
level: 4
scenario: >
  What the user is trying to get the AI to do.
fixed_context: null          # or a document attached after the prompt; never removed
requirements:
  - id: on_task
    label: "Actually does the task"
    short: "actually doing the task"
    scorer: on_topic
    params: { any_of: ["word", "another"] }
    gate: true               # a gate multiplies the score: fail it and the answer scores 0
  - id: length
    label: "60 words or fewer"
    short: "length"
    scorer: word_count_max   # any scorer in core/scorers.py
    params: { max: 60 }
reference_prompt: >
  A prompt that passes every check.
```

Then run `scripts/verify_references.py` to make sure the reference prompt passes 5 out of 5 times.

## What I'd do next

- Use KernelSHAP over prompt parts, to catch parts that only matter in combination.
- Run a study with real users: do they write better prompts after using this, and do they over-trust it?
- Add tasks that probe responsible AI issues more directly, such as identity swaps for bias, sycophancy, and refusals.
- Compare the same prompts across several models.
