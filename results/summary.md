# Evaluation summary

Model: claude-haiku-5-5. Settings: 3 baseline runs, 2 runs per removed part, each part's noise floor = max(2 × standard error of its with/without difference, 0.05).
Attempts: 240 synthetic prompts (8 challenges × 3 personas × 10). Analyses completed: 240.
Parts per prompt: median 3, range 1–8. Segmentation: 239 by the model, 1 by the regex fallback.
Failed calls or analyses logged: 0.

Mean overall score of the full prompt, by persona (sanity check on the synthetic prompts):

| Challenge | Novice | Average | Expert |
|---|---|---|---|
| explain_to_kid | 0.36 | 0.52 | 0.94 |
| landlord_reply | 0.79 | 0.84 | 1.00 |
| job_extraction | 0.06 | 0.64 | 0.84 |
| meeting_summary | 0.76 | 0.93 | 1.00 |
| shopping_list | 0.59 | 0.65 | 1.00 |
| subject_line | 0.70 | 0.91 | 1.00 |
| privacy_bug_report | 0.87 | 0.91 | 1.00 |
| faq_only | 0.61 | 0.73 | 0.95 |
| **all** | **0.59** | **0.77** | **0.97** |

## A. Noise floor

Baseline std is the run-to-run spread of a score over 3 runs of the same prompt.

| Challenge | Target | Mean std | Max std | Runs with zero std | Mean floor | Parts above floor |
|---|---|---|---|---|---|---|
| explain_to_kid | bullets | 0.075 | 0.577 | 77% | 0.210 | 37/103 (36%) |
| explain_to_kid | length | 0.041 | 0.311 | 70% | 0.119 | 30/103 (29%) |
| explain_to_kid | on_task | 0.000 | 0.000 | 100% | 0.050 | 24/103 (23%) |
| explain_to_kid | overall | 0.063 | 0.231 | 13% | 0.118 | 70/103 (68%) |
| explain_to_kid | reading_level | 0.106 | 0.314 | 20% | 0.208 | 44/103 (43%) |
| faq_only | admits_gap | 0.096 | 0.577 | 83% | 0.235 | 16/92 (17%) |
| faq_only | length | 0.095 | 0.406 | 37% | 0.188 | 29/92 (32%) |
| faq_only | no_guessing | 0.231 | 0.577 | 60% | 0.506 | 21/92 (23%) |
| faq_only | on_task | 0.000 | 0.000 | 100% | 0.056 | 21/92 (23%) |
| faq_only | overall | 0.102 | 0.322 | 20% | 0.206 | 30/92 (33%) |
| job_extraction | accuracy | 0.005 | 0.144 | 97% | 0.059 | 26/84 (31%) |
| job_extraction | fields | 0.000 | 0.000 | 100% | 0.054 | 27/84 (32%) |
| job_extraction | json_only | 0.000 | 0.000 | 100% | 0.070 | 24/84 (29%) |
| job_extraction | no_invented_salary | 0.019 | 0.577 | 97% | 0.092 | 13/84 (15%) |
| job_extraction | overall | 0.006 | 0.144 | 93% | 0.063 | 39/84 (46%) |
| landlord_reply | cites_facts | 0.000 | 0.000 | 100% | 0.050 | 0/97 (0%) |
| landlord_reply | length | 0.082 | 0.410 | 30% | 0.180 | 35/97 (36%) |
| landlord_reply | no_apology | 0.000 | 0.000 | 100% | 0.050 | 0/97 (0%) |
| landlord_reply | on_task | 0.000 | 0.000 | 100% | 0.095 | 4/97 (4%) |
| landlord_reply | overall | 0.027 | 0.137 | 30% | 0.110 | 34/97 (35%) |
| meeting_summary | key_facts | 0.000 | 0.000 | 100% | 0.066 | 3/91 (3%) |
| meeting_summary | length | 0.038 | 0.144 | 57% | 0.105 | 24/91 (26%) |
| meeting_summary | no_noise | 0.032 | 0.192 | 83% | 0.129 | 11/91 (12%) |
| meeting_summary | on_task | 0.000 | 0.000 | 100% | 0.066 | 1/91 (1%) |
| meeting_summary | overall | 0.023 | 0.109 | 57% | 0.090 | 19/91 (21%) |
| privacy_bug_report | keeps_details | 0.000 | 0.000 | 100% | 0.075 | 1/94 (1%) |
| privacy_bug_report | length | 0.067 | 0.293 | 50% | 0.147 | 24/94 (26%) |
| privacy_bug_report | no_personal_info | 0.019 | 0.577 | 97% | 0.104 | 12/94 (13%) |
| privacy_bug_report | on_task | 0.000 | 0.000 | 100% | 0.050 | 1/94 (1%) |
| privacy_bug_report | overall | 0.029 | 0.192 | 47% | 0.087 | 26/94 (28%) |
| shopping_list | needed_items | 0.000 | 0.000 | 100% | 0.088 | 4/88 (5%) |
| shopping_list | no_steps | 0.029 | 0.433 | 93% | 0.137 | 10/88 (11%) |
| shopping_list | on_task | 0.019 | 0.577 | 97% | 0.101 | 8/88 (9%) |
| shopping_list | one_per_line | 0.082 | 0.382 | 57% | 0.201 | 16/88 (18%) |
| shopping_list | overall | 0.034 | 0.361 | 57% | 0.099 | 26/88 (30%) |
| shopping_list | skips_pantry | 0.000 | 0.000 | 100% | 0.109 | 14/88 (16%) |
| subject_line | has_number | 0.000 | 0.000 | 100% | 0.082 | 1/92 (1%) |
| subject_line | not_salesy | 0.000 | 0.000 | 100% | 0.057 | 3/92 (3%) |
| subject_line | on_task | 0.000 | 0.000 | 100% | 0.103 | 2/92 (2%) |
| subject_line | one_short_line | 0.077 | 0.577 | 87% | 0.156 | 19/92 (21%) |
| subject_line | overall | 0.026 | 0.192 | 87% | 0.111 | 16/92 (17%) |

Overall score: 260 of 741 parts (35%) had an effect above the noise floor.

## B. Faithfulness (deletion test)

Attempts with at least 4 parts: 79. For each, we removed the top-k parts by |overall attribution| together (2 fresh runs) and k random parts (5 random draws, one fresh run each), and measured the drop in overall score from the full prompt.

| k | n | Mean drop, top-k [95% CI] | Mean drop, random [95% CI] | Top-k larger | Wilcoxon p (one-sided) |
|---|---|---|---|---|---|
| 2 | 79 | 0.303 [0.222, 0.389] | 0.182 [0.137, 0.231] | 42/79 | 0.00023 |
| 3 | 79 | 0.362 [0.282, 0.444] | 0.347 [0.285, 0.411] | 39/79 | 0.46 |

- explain_to_kid, k = 2: top-k drop 0.774, random drop 0.448 (n = 13)
- landlord_reply, k = 2: top-k drop 0.053, random drop 0.063 (n = 11)
- job_extraction, k = 2: top-k drop 0.601, random drop 0.274 (n = 6)
- meeting_summary, k = 2: top-k drop 0.009, random drop 0.032 (n = 9)
- shopping_list, k = 2: top-k drop 0.222, random drop 0.161 (n = 10)
- subject_line, k = 2: top-k drop 0.155, random drop 0.080 (n = 8)
- privacy_bug_report, k = 2: top-k drop 0.156, random drop 0.074 (n = 12)
- faq_only, k = 2: top-k drop 0.424, random drop 0.283 (n = 10)

## C. Stability

80 attempts were analyzed a second time with the same parts (fresh model calls).

- Spearman correlation of overall attributions between the two runs: mean 0.77, median 1.00 (n = 35; 45 attempts had fewer than 3 parts or constant attributions).
- Same top-1 part in both runs: 62/80 (78%). Among attempts whose top part cleared the noise floor in run 1: 42/49 (86%).
- Same verdict (helped / hurt / no effect) per part: 81% of parts.
- Segmentation: each of 80 prompts was segmented 3 times. Identical boundaries in all 3: 71/80 (89%); identical boundaries and roles: 66/80 (82%). Pairwise identical boundaries: 221/240 (92%). Regex fallback used in 3 of 240 segmentations.

## D. Which prompt parts mattered, by role

All 741 parts from the 240 analyses, grouped by the role the segmenter gave them. Effect = |overall attribution|.

| Role | Parts | Mean effect | Mean signed effect | Above noise floor |
|---|---|---|---|---|
| format | 50 | 0.240 | +0.236 | 70% |
| task | 258 | 0.231 | +0.198 | 44% |
| audience | 32 | 0.159 | +0.077 | 44% |
| context | 84 | 0.125 | +0.062 | 36% |
| other | 4 | 0.120 | +0.043 | 25% |
| constraint | 259 | 0.076 | +0.062 | 22% |
| politeness_filler | 36 | 0.062 | -0.012 | 17% |
| tone | 18 | 0.036 | -0.004 | 22% |

## E. Per-part check (did the answers do what each part asked?)

An AI rated every answer against every part of its prompt (yes / partly / no / n/a). 240 analyses, 2202 judged answers, 0 judgements unusable. A part mattered if the task score dropped without it. It counts as "AI followed it" if answers did it with the part and mostly stopped without it (mean rating gap ≥ 0.5) while the score didn't move.

| Role | Parts | Mattered | AI followed it | Hurt | AI did it anyway | Ignored | Not clear | Nothing to act on |
|---|---|---|---|---|---|---|---|---|
| constraint | 259 | 20% | 7% | 2% | 61% | 1% | 9% | 0% |
| task | 258 | 39% | 9% | 5% | 40% | 0% | 7% | 0% |
| context | 84 | 19% | 1% | 17% | 43% | 0% | 7% | 13% |
| format | 50 | 70% | 12% | 0% | 14% | 0% | 4% | 0% |
| politeness_filler | 36 | 8% | 0% | 8% | 3% | 0% | 19% | 61% |
| audience | 32 | 31% | 3% | 12% | 47% | 0% | 6% | 0% |
| tone | 18 | 11% | 0% | 11% | 78% | 0% | 0% | 0% |
| other | 4 | 25% | 25% | 0% | 25% | 0% | 25% | 0% |

All parts: mattered 218, followed 50, hurt 42, anyway 335, ignored 2, unclear 60, quiet 34 (of 741).
- explain_to_kid: mattered 64, followed 1, hurt 6, anyway 24, ignored 0, unclear 6, quiet 2
- faq_only: mattered 26, followed 1, hurt 4, anyway 29, ignored 0, unclear 31, quiet 1
- job_extraction: mattered 31, followed 8, hurt 8, anyway 29, ignored 0, unclear 1, quiet 7
- landlord_reply: mattered 17, followed 2, hurt 17, anyway 54, ignored 0, unclear 5, quiet 2
- meeting_summary: mattered 17, followed 12, hurt 2, anyway 52, ignored 0, unclear 1, quiet 7
- privacy_bug_report: mattered 23, followed 10, hurt 3, anyway 50, ignored 0, unclear 4, quiet 4
- shopping_list: mattered 25, followed 5, hurt 1, anyway 46, ignored 2, unclear 3, quiet 6
- subject_line: mattered 15, followed 11, hurt 1, anyway 51, ignored 0, unclear 9, quiet 5

Stability: in the 80 attempts analyzed twice, 168/234 parts (72%) got the same verdict both times.

## F. Judge vs code checks

Some prompt parts ask for exactly what a code check measures ("under 60 words", "exactly 3 bullets", "only JSON", "don't apologize", "keep the customer's details out"). For those parts, the judge's rating of every saved answer can be compared with the code check on the same answer. 102 parts in 78 analyses, 1187 rated answers; the judge said "partly" on 4% of them.

| Check | Answers | Judge yes / code pass | Judge no / code fail | Judge yes / code fail | Judge no / code pass | Agreement | Kappa |
|---|---|---|---|---|---|---|---|
| bullets | 145 | 96 | 43 | 0 | 6 | 96% | 0.90 |
| json_only | 89 | 43 | 40 | 0 | 6 | 93% | 0.87 |
| length | 601 | 475 | 17 | 93 | 16 | 82% | 0.17 |
| no_apology | 67 | 67 | 0 | 0 | 0 | 100% | nan |
| no_personal_info | 151 | 142 | 0 | 6 | 3 | 94% | -0.03 |
| one_short_line | 86 | 77 | 1 | 8 | 0 | 91% | 0.18 |
| **all** | 1139 | 900 | 101 | 107 | 31 | 88% | 0.53 |

Agreement and kappa leave out "partly". The code check is the reference here, so a disagreement is usually the judge's mistake, though a few are wording mismatches (a part that says "short" next to a number, for example).

## Cost

The 240 main analyses used 3805 calls and 2,427,494 tokens (~$0.44). Faithfulness, stability, and segmentation reruns are counted in results/eval_cost.json.
