# Phase 2 checkpoint findings

Model: claude-haiku-5-5, thinking off, effort low, temperature unset (the model rejects non-default values).
Date: 2026-10-16. Total Phase 2 spend, including two earlier batches and debugging: about 500 calls, about $0.05.

Final settings: `baseline_runs: 3`, `ablation_runs: 2`, `max_tokens: 800`, `max_calls_per_analysis: 30`.
Final results: `results/phase2/` (full output in `checkpoint_output.txt`).
The first two batches (1 and 2 ablation runs, before the fixes below) are in `results/archive/`.

## Reference prompts

All three pass every requirement on 5 of 5 runs (`results/reference_check.json`).
The explain-to-kid reference first passed reading level on only 3 of 5 runs (grade 5.2 to 5.8).
Adding "Keep every sentence under 10 words" fixed it.

## Go/no-go

Rule: the obvious segment's attribution clears the noise floor in at least 2 of 3 challenges.
Result: GO, 3 of 3.

| Challenge | Segment | Requirement | Attribution | Noise floor |
|---|---|---|---|---|
| explain_to_kid | "Keep it under 60 words." | length | +0.63 | 0.05 |
| explain_to_kid | "and exactly 3 bullets." | bullets | +1.00 | 0.05 |
| explain_to_kid | "in under 60 words," | length | +0.94 | 0.14 |
| landlord_reply | "Keep it under 120 words." | length | +0.35 | 0.05 |
| job_extraction | "No code fences." | json_only | +0.50 | 0.05 |
| job_extraction | "Write work_mode as a single word." | accuracy | +0.25 | 0.05 |

These three expected effects did not appear:

| Segment | Requirement | Attribution | Why |
|---|---|---|---|
| "Be firm and don't apologize." | no_apology | 0.00 | The model never apologizes, with or without it |
| "Cite the lease section." | cites_facts | 0.00 | The model cites the attached lease either way |
| "Use null if a field is missing." | no_invented_salary | 0.00 | The model never invents a salary either way |

## What we found and changed

1. **Some requirements don't depend on the prompt with this model.**
   No-apology, cites-facts and no-invented-salary scored 1.0 on nearly every answer.
   To give the model a real chance to fail, both documents were changed:
   - The landlord email now guilt-trips the tenant ("We were disappointed...").
   - The lease excerpt now has four sections instead of one.
   - The job posting now has a "$2,000 sign-on bonus" as a decoy for the salary field.

   Across 30 probe runs with weak prompts, the model still never apologized, always cited the lease, and never put the bonus in `salary`.
   We kept the plan's requirements and report this as a result.
   The heatmap correctly gives these requirements no effect from any part of the prompt.
2. **One ablation run reported false effects.**
   With 1 run, "Thanks so much!" showed +0.29 on reading level, above its noise floor.
   With 2 runs it was within noise.
   `ablation_runs` is now 2, and `max_calls_per_analysis` is now 30 (10 segments need 27 calls).
3. **max_tokens 400 truncated 5 of 145 answers.**
   A cut-off JSON answer can't be parsed, so it scored 0 on everything.
   The cap is now 800. There was no truncation in the final batch (89 answers).
4. **Scorer bug: the model's own intro line counted as an apology.**
   "Here's a firm reply that doesn't apologize:" contains the word "apologize".
   `keywords_absent` now ignores a keyword when a negation comes just before it.
5. **Segmentation fell back to the regex split too often.**
   The model drops end periods and connecting words like "and" when it copies parts back.
   Before the fix, 4 of 6 tries on one prompt failed validation.
   Alignment now tolerates dropped edge punctuation and a dropped leading connector word; every other word must still match.
   In a 27-call test, 25 were valid even before the connector fix.
   In the final batch, all 9 used the model's segmentation.
6. **"Output only JSON" doesn't stop code fences; "No code fences" does.**
   This is a real effect worth using as a demo example.
7. **The same prompt can be split differently on different runs.**
   For example, "Explain inflation to a 10-year-old." was one segment in one batch and two in another.
   This will show up in the Phase 4 stability eval.
8. **Noise floors from 3 baseline runs vary a lot when the requirement itself varies.**
   In case 2, the reading-level floor ranged from 0.21 to 0.68 across batches.
   Reading level is the noisiest requirement.
