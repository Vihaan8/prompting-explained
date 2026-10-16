# Evaluation summary

Model: claude-haiku-5-5. Settings: 3 baseline runs, 2 runs per removed part, noise floor = max(2 × std, 0.05).
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
| explain_to_kid | bullets | 0.075 | 0.577 | 77% | 0.189 | 43/103 (42%) |
| explain_to_kid | length | 0.041 | 0.311 | 70% | 0.118 | 38/103 (37%) |
| explain_to_kid | on_task | 0.000 | 0.000 | 100% | 0.050 | 24/103 (23%) |
| explain_to_kid | overall | 0.063 | 0.231 | 13% | 0.134 | 68/103 (66%) |
| explain_to_kid | reading_level | 0.106 | 0.314 | 20% | 0.225 | 42/103 (41%) |
| job_extraction | accuracy | 0.005 | 0.144 | 97% | 0.058 | 28/84 (33%) |
| job_extraction | fields | 0.000 | 0.000 | 100% | 0.050 | 29/84 (35%) |
| job_extraction | json_only | 0.000 | 0.000 | 100% | 0.050 | 30/84 (36%) |
| job_extraction | no_invented_salary | 0.019 | 0.577 | 97% | 0.087 | 14/84 (17%) |
| job_extraction | overall | 0.006 | 0.144 | 93% | 0.059 | 46/84 (55%) |
| landlord_reply | cites_facts | 0.000 | 0.000 | 100% | 0.050 | 0/97 (0%) |
| landlord_reply | length | 0.082 | 0.410 | 30% | 0.180 | 35/97 (36%) |
| landlord_reply | no_apology | 0.000 | 0.000 | 100% | 0.050 | 0/97 (0%) |
| landlord_reply | on_task | 0.000 | 0.000 | 100% | 0.050 | 8/97 (8%) |
| landlord_reply | overall | 0.027 | 0.137 | 30% | 0.074 | 36/97 (37%) |

Overall score: 150 of 284 parts (53%) had an effect above the noise floor.

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
| task | 97 | 0.263 | +0.230 | 56% |
| audience | 22 | 0.198 | +0.132 | 55% |
| context | 39 | 0.134 | +0.035 | 46% |
| constraint | 70 | 0.093 | +0.073 | 46% |
| other | 3 | 0.086 | -0.017 | 0% |
| politeness_filler | 12 | 0.073 | +0.037 | 25% |
| tone | 9 | 0.059 | -0.020 | 33% |

## E. Per-part check (did the answers do what each part asked?)

An AI rated every answer against every part of its prompt (yes / partly / no / n/a). 90 analyses, 838 judged answers, 0 judgements unusable. A part is shown as mattered if the task score dropped without it, or if answers did it with the part but mostly stopped without it (mean rating gap ≥ 0.5).

| Role | Parts | Mattered | Hurt | AI did it anyway | Ignored | Not clear | Nothing to act on |
|---|---|---|---|---|---|---|---|
| task | 97 | 53% | 9% | 38% | 0% | 0% | 0% |
| constraint | 70 | 41% | 9% | 50% | 0% | 0% | 0% |
| context | 39 | 21% | 31% | 38% | 0% | 0% | 10% |
| format | 32 | 88% | 3% | 9% | 0% | 0% | 0% |
| audience | 22 | 45% | 14% | 36% | 0% | 5% | 0% |
| politeness_filler | 12 | 17% | 8% | 0% | 0% | 25% | 50% |
| tone | 9 | 11% | 22% | 67% | 0% | 0% | 0% |
| other | 3 | 0% | 0% | 100% | 0% | 0% | 0% |

All parts: mattered 129, hurt 34, anyway 107, ignored 0, unclear 4, quiet 10 (of 284).
- explain_to_kid: mattered 65, hurt 8, anyway 25, ignored 0, unclear 3, quiet 2
- job_extraction: mattered 42, hurt 10, anyway 25, ignored 0, unclear 0, quiet 7
- landlord_reply: mattered 22, hurt 16, anyway 57, ignored 0, unclear 1, quiet 1

Stability: in the 30 attempts analyzed twice, 64/88 parts (73%) got the same verdict both times.

## Cost

The 90 main analyses used 927 calls and 481,263 tokens (~$0.13). Faithfulness, stability, and segmentation reruns are counted in results/eval_cost.json.
