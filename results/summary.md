# Evaluation summary

Model: claude-haiku-5-5. Settings: 3 baseline runs, 2 runs per removed part, each part's noise floor = max(2 × standard error of its with/without difference, 0.05).
Attempts: 90 synthetic prompts (3 challenges × 3 personas × 10). Analyses completed: 90.
Parts per prompt: median 3, range 1–6. Segmentation: 89 by the model, 1 by the regex fallback.
Failed calls or analyses logged: 0.

Mean overall score of the full prompt, by persona (sanity check on the synthetic prompts):

| Challenge | Novice | Average | Expert |
|---|---|---|---|
| explain_to_kid | 0.36 | 0.52 | 0.94 |
| landlord_reply | 0.79 | 0.84 | 1.00 |
| job_extraction | 0.06 | 0.64 | 0.84 |

## A. Noise floor

Baseline std is the run-to-run spread of a score over 3 runs of the same prompt.

| Challenge | Target | Mean std | Max std | Runs with zero std | Mean floor | Parts above floor |
|---|---|---|---|---|---|---|
| explain_to_kid | bullets | 0.075 | 0.577 | 77% | 0.210 | 37/103 (36%) |
| explain_to_kid | length | 0.041 | 0.311 | 70% | 0.119 | 30/103 (29%) |
| explain_to_kid | on_task | 0.000 | 0.000 | 100% | 0.050 | 24/103 (23%) |
| explain_to_kid | overall | 0.063 | 0.231 | 13% | 0.118 | 70/103 (68%) |
| explain_to_kid | reading_level | 0.106 | 0.314 | 20% | 0.208 | 44/103 (43%) |
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

Overall score: 143 of 284 parts (50%) had an effect above the noise floor.

## B. Faithfulness (deletion test)

Attempts with at least 4 parts: 30. For each, we removed the top-k parts by |overall attribution| together (2 fresh runs) and k random parts (5 random draws, one fresh run each), and measured the drop in overall score from the full prompt.

| k | n | Mean drop, top-k [95% CI] | Mean drop, random [95% CI] | Top-k larger | Wilcoxon p (one-sided) |
|---|---|---|---|---|---|
| 2 | 30 | 0.475 [0.329, 0.628] | 0.272 [0.182, 0.370] | 24/30 | 0.00024 |
| 3 | 30 | 0.489 [0.349, 0.632] | 0.507 [0.397, 0.623] | 14/30 | 0.61 |

- explain_to_kid, k = 2: top-k drop 0.774, random drop 0.448 (n = 13)
- landlord_reply, k = 2: top-k drop 0.053, random drop 0.063 (n = 11)
- job_extraction, k = 2: top-k drop 0.601, random drop 0.274 (n = 6)

## C. Stability

30 attempts were analyzed a second time with the same parts (fresh model calls).

- Spearman correlation of overall attributions between the two runs: mean 0.85, median 1.00 (n = 17; 13 attempts had fewer than 3 parts or constant attributions).
- Same top-1 part in both runs: 25/30 (83%). Among attempts whose top part cleared the noise floor in run 1: 17/20 (85%).
- Same verdict (helped / hurt / no effect) per part: 76% of parts.
- Segmentation: each of 30 prompts was segmented 3 times. Identical boundaries in all 3: 25/30 (83%); identical boundaries and roles: 22/30 (73%). Pairwise identical boundaries: 80/90 (89%). Regex fallback used in 3 of 90 segmentations.

## D. Which prompt parts mattered, by role

All 284 parts from the 90 analyses, grouped by the role the segmenter gave them. Effect = |overall attribution|.

| Role | Parts | Mean effect | Mean signed effect | Above noise floor |
|---|---|---|---|---|
| format | 32 | 0.270 | +0.266 | 88% |
| task | 97 | 0.263 | +0.230 | 54% |
| audience | 22 | 0.198 | +0.132 | 55% |
| context | 39 | 0.134 | +0.035 | 49% |
| constraint | 70 | 0.093 | +0.073 | 36% |
| other | 3 | 0.086 | -0.017 | 33% |
| politeness_filler | 12 | 0.073 | +0.037 | 25% |
| tone | 9 | 0.059 | -0.020 | 33% |

## E. Per-part check (did the answers do what each part asked?)

An AI rated every answer against every part of its prompt (yes / partly / no / n/a). 90 analyses, 838 judged answers, 0 judgements unusable. A part mattered if the task score dropped without it. It counts as "AI followed it" if answers did it with the part and mostly stopped without it (mean rating gap ≥ 0.5) while the score didn't move.

| Role | Parts | Mattered | AI followed it | Hurt | AI did it anyway | Ignored | Not clear | Nothing to act on |
|---|---|---|---|---|---|---|---|---|
| task | 97 | 44% | 5% | 9% | 37% | 0% | 4% | 0% |
| constraint | 70 | 30% | 6% | 6% | 57% | 0% | 1% | 0% |
| context | 39 | 15% | 3% | 33% | 33% | 0% | 5% | 10% |
| format | 32 | 88% | 0% | 0% | 9% | 0% | 3% | 0% |
| audience | 22 | 45% | 5% | 9% | 36% | 0% | 5% | 0% |
| politeness_filler | 12 | 17% | 0% | 8% | 0% | 0% | 17% | 58% |
| tone | 9 | 11% | 0% | 22% | 67% | 0% | 0% | 0% |
| other | 3 | 33% | 0% | 0% | 33% | 0% | 33% | 0% |

All parts: mattered 112, followed 11, hurt 31, anyway 107, ignored 0, unclear 12, quiet 11 (of 284).
- explain_to_kid: mattered 64, followed 1, hurt 6, anyway 24, ignored 0, unclear 6, quiet 2
- job_extraction: mattered 31, followed 8, hurt 8, anyway 29, ignored 0, unclear 1, quiet 7
- landlord_reply: mattered 17, followed 2, hurt 17, anyway 54, ignored 0, unclear 5, quiet 2

Stability: in the 30 attempts analyzed twice, 62/88 parts (70%) got the same verdict both times.

## Cost

The 90 main analyses used 927 calls and 481,263 tokens (~$0.13). Faithfulness, stability, and segmentation reruns are counted in results/eval_cost.json.
