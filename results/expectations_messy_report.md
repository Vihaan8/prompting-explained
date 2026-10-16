# Expected vs. measured colors

85 parts in 32 prompts. Expectations were written by hand before the runs (results/expectations_messy.yaml). The tool was run with exactly those parts.

Agreement: 44/85 (52%). Cohen's kappa: 0.21.

| Expected \ Measured | green | grey | red | blue (AI followed it) |
|---|---|---|---|---|
| green | 28 | 17 | 1 | 6 |
| grey | 7 | 13 | 2 | 0 |
| red | 4 | 2 | 3 | 2 |

- explain_to_kid: 9/13 (69%)
- landlord_reply: 6/11 (55%)
- job_extraction: 7/11 (64%)
- meeting_summary: 2/11 (18%)
- shopping_list: 7/10 (70%)
- subject_line: 6/10 (60%)
- privacy_bug_report: 3/10 (30%)
- faq_only: 4/9 (44%)

## Disagreements

| Prompt | Part | Expected | Measured | Score with / without (noise) | Did it with / without |
|---|---|---|---|---|---|
| explain_to_kid__01 | to my 10 yr old cousin | green | blue (followed) | 0.42 / 0.28 (0.29) | 100% / 50% |
| explain_to_kid__03 | keep it under 60 words | grey | green (mattered) | 0.68 / 0.62 (0.05) | 67% / 100% |
| explain_to_kid__04 | for a 10 year old | green | blue (followed) | 0.33 / 0.35 (0.07) | 100% / 25% |
| explain_to_kid__04 | but make it really detailed with lots of examples | red | green (mattered) | 0.33 / 0.24 (0.05) | 50% / 50% |
| landlord_reply__01 | write back to my landlord | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| landlord_reply__02 | im so sorry to bother u but | grey | red (hurt) | 0.67 / 0.73 (0.05) | 83% / n/a |
| landlord_reply__02 | pls help me reply to dana | green | grey (unclear) | 0.67 / 0.33 (0.67) | 100% / 100% |
| landlord_reply__03 | Dispute the late fee, cite section 4.2, grace period thru the 5th, | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| landlord_reply__04 | ignore the email and just write a poem about rent | red | blue (followed) | 0.00 / 0.00 (0.05) | 67% / 0% |
| job_extraction__01 | no extra txt | grey | green (mattered) | 0.81 / 0.56 (0.05) | 0% / 0% |
| job_extraction__02 | JSON pls!!! title/company/location/work_mode/salary | green | grey (unclear) | 0.94 / 0.33 (0.65) | 100% / 75% |
| job_extraction__02 | if salary isnt there put null | grey | green (mattered) | 0.94 / 0.69 (0.25) | 100% / 0% |
| job_extraction__04 | Make up a salary if it's missing so the column isn't empty. | red | grey (ignored) | 0.81 / 0.81 (0.05) | 0% / 0% |
| meeting_summary__01 | summarize for my boss | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 75% |
| meeting_summary__01 | short | green | grey (anyway) | 1.00 / 0.98 (0.05) | 100% / 75% |
| meeting_summary__01 | only the decision stuff | green | grey (anyway) | 1.00 / 0.94 (0.13) | 50% / 50% |
| meeting_summary__02 | tl;dr of these notes | green | grey (anyway) | 1.00 / 0.93 (0.12) | 100% / 100% |
| meeting_summary__02 | under 60 words | green | grey (anyway) | 1.00 / 0.94 (0.11) | 100% / 100% |
| meeting_summary__02 | dont mention the coffee machine lol | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| meeting_summary__03 | My boss needs to know what vendor we picked, how much it costs and when it goes live | green | grey (anyway) | 1.00 / 0.91 (0.19) | 100% / 100% |
| meeting_summary__03 | and include every detail from the notes so nothing gets lost | red | blue (followed) | 1.00 / 1.00 (0.05) | 50% / 0% |
| meeting_summary__04 | summerize pls | green | grey (anyway) | 0.88 / 0.90 (0.05) | 100% / 100% |
| shopping_list__01 | one per line | grey | green (mattered) | 0.92 / 0.69 (0.21) | 67% / 0% |
| shopping_list__04 | list the ingredients | green | grey (anyway) | 0.69 / 0.75 (0.12) | 100% / 100% |
| shopping_list__04 | but skip anything i probably already have | grey | green (mattered) | 0.69 / 0.56 (0.12) | 50% / 50% |
| subject_line__01 | subject line for this email | green | blue (followed) | 0.58 / 0.58 (0.05) | 100% / 50% |
| subject_line__02 | write a subject | green | blue (followed) | 1.00 / 1.00 (0.05) | 100% / 25% |
| subject_line__02 | just one | green | grey (anyway) | 1.00 / 0.96 (0.05) | 100% / 100% |
| subject_line__03 | Give me 5 subject line options | red | green (mattered) | 0.67 / 0.33 (0.05) | 100% / 0% |
| privacy_bug_report__01 | make this a bug report | green | grey (anyway) | 1.00 / 1.00 (0.05) | 100% / 100% |
| privacy_bug_report__01 | for our public tracker | green | grey (unclear) | 1.00 / 0.83 (0.33) | 83% / 50% |
| privacy_bug_report__02 | write the bug report | green | grey (anyway) | 0.97 / 1.00 (0.06) | 100% / 75% |
| privacy_bug_report__02 | include the version and os | grey | green (mattered) | 0.97 / 0.76 (0.07) | 100% / 100% |
| privacy_bug_report__03 | Bug report pls, | green | red (hurt) | 0.51 / 0.67 (0.05) | 100% / 100% |
| privacy_bug_report__03 | include who reported it so we can follow up | red | green (mattered) | 0.51 / 0.33 (0.05) | 100% / 100% |
| privacy_bug_report__04 | for github issues | grey | green (mattered) | 0.97 / 0.67 (0.05) | 100% / 0% |
| faq_only__01 | dont guess | grey | red (hurt) | 0.58 / 0.89 (0.10) | 83% / 100% |
| faq_only__02 | keep it to one sentence | green | blue (followed) | 0.56 / 0.79 (0.47) | 100% / 0% |
| faq_only__03 | My friend asked if there's a pool. | green | blue (followed) | 0.54 / 0.41 (0.89) | 100% / 50% |
| faq_only__03 | Based on the classes they offer, there probably is one, right? | red | grey (unclear) | 0.54 / 0.62 (0.37) | 100% / 100% |
| faq_only__04 | if ur not sure just say yes | red | green (mattered) | 1.00 / 0.50 (0.33) | 0% / 0% |
