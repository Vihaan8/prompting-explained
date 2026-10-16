# Expected vs. measured colors

71 parts in 24 prompts. Expectations were written by hand before the runs (results/expectations.yaml). The tool was run with exactly those parts.

Agreement: 59/71 (83%). Cohen's kappa: 0.71.

| Expected \ Measured | green | grey | red |
|---|---|---|---|
| green | 33 | 8 | 0 |
| grey | 2 | 19 | 0 |
| red | 1 | 1 | 7 |

- explain_to_kid: 24/26 (92%)
- landlord_reply: 19/24 (79%)
- job_extraction: 16/21 (76%)

## Disagreements

| Prompt | Part | Expected | Measured | Score with / without (noise) | Did it with / without |
|---|---|---|---|---|---|
| explain_to_kid__05 | You are a friendly teacher. | grey | green (mattered) | 0.66 / 0.55 (0.05) | 50% / 50% |
| explain_to_kid__05 | with a candy example. | grey | green (mattered) | 0.66 / 0.61 (0.05) | 100% / 0% |
| landlord_reply__02 | Write a reply to my landlord. | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| landlord_reply__05 | Draft an email reply to Dana | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| landlord_reply__05 | Keep it brief, under 100 words. | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| landlord_reply__06 | Keep it under 120 words. | green | grey (anyway) | 1.00 / 0.96 (0.05) | 100% / 100% |
| landlord_reply__07 | Reply to this email and dispute the fee. | green | grey (unclear) | 0.83 / 0.94 (0.25) | 100% / 100% |
| job_extraction__01 | Extract the job details from this posting as JSON | green | grey (anyway) | 0.94 / 0.97 (0.05) | 100% / 100% |
| job_extraction__03 | Wrap it in a markdown code block. | red | grey (ignored) | 0.81 / 0.81 (0.05) | 0% / 0% |
| job_extraction__04 | Write work_mode as a single word. | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| job_extraction__05 | After the JSON, add a one-sentence summary of the role. | red | green (mattered) | 0.81 / 0.81 (0.05) | 100% / 0% |
| job_extraction__08 | Make a JSON object for this job posting | green | grey (anyway) | 0.81 / 0.81 (0.05) | 100% / 100% |
