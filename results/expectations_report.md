# Expected vs. measured colors

71 parts in 24 prompts. Expectations were written by hand before the runs (results/expectations.yaml). The tool was run with exactly those parts.

Agreement: 54/71 (76%). Cohen's kappa: 0.60.

| Expected \ Measured | green | grey | red | blue (AI followed it) |
|---|---|---|---|---|
| green | 31 | 8 | 0 | 2 |
| grey | 3 | 18 | 0 | 0 |
| red | 0 | 1 | 5 | 3 |

- explain_to_kid: 22/26 (85%)
- landlord_reply: 17/24 (71%)
- job_extraction: 15/21 (71%)

## Disagreements

| Prompt | Part | Expected | Measured | Score with / without (noise) | Did it with / without |
|---|---|---|---|---|---|
| explain_to_kid__01 | Keep it under 60 words. | green | blue (followed) | 0.93 / 0.60 (0.36) | 100% / 50% |
| explain_to_kid__05 | You are a friendly teacher. | grey | green (mattered) | 0.66 / 0.55 (0.10) | 50% / 50% |
| explain_to_kid__05 | with a candy example. | grey | green (mattered) | 0.66 / 0.61 (0.05) | 100% / 0% |
| explain_to_kid__07 | Hi! | grey | green (mattered) | 0.92 / 0.81 (0.09) | n/a / n/a |
| landlord_reply__02 | Write a reply to my landlord. | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| landlord_reply__04 | Write a reply to my landlord disputing the late fee. | green | blue (followed) | 0.67 / 0.33 (0.67) | 100% / 50% |
| landlord_reply__04 | Make it detailed and thorough, at least 200 words. | red | blue (followed) | 0.67 / 0.83 (0.19) | 100% / 25% |
| landlord_reply__05 | Draft an email reply to Dana | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| landlord_reply__05 | Keep it brief, under 100 words. | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| landlord_reply__06 | Keep it under 120 words. | green | grey (anyway) | 1.00 / 0.96 (0.05) | 100% / 100% |
| landlord_reply__07 | Reply to this email and dispute the fee. | green | grey (anyway) | 0.83 / 0.94 (0.15) | 100% / 100% |
| job_extraction__01 | Extract the job details from this posting as JSON | green | grey (anyway) | 0.94 / 0.97 (0.06) | 100% / 100% |
| job_extraction__03 | Wrap it in a markdown code block. | red | grey (ignored) | 0.81 / 0.81 (0.05) | 0% / 0% |
| job_extraction__04 | Write work_mode as a single word. | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| job_extraction__05 | After the JSON, add a one-sentence summary of the role. | red | blue (followed) | 0.81 / 0.81 (0.05) | 100% / 0% |
| job_extraction__07 | Include every other detail from the posting too, like perks and requirements. | red | blue (followed) | 0.81 / 0.88 (0.12) | 100% / 25% |
| job_extraction__08 | Make a JSON object for this job posting | green | grey (anyway) | 0.81 / 0.81 (0.05) | 100% / 100% |
