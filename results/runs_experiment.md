# How many runs are enough?

Model: claude-haiku-5-5. 80 prompts from the stability subset, each run 12 times in full and 12 times per removed part, with the same parts as the main analysis. For each setting, two disjoint random subsets of those runs were scored as separate analyses and compared (25 random pairs per prompt). The app uses 3/2. "Same top part" counts only the 71 prompts with at least 2 parts.

| Full runs / runs per part | Task calls per analysis (mean) | Same verdict per part | Same top part | Parts shown as no effect |
|---|---|---|---|---|
| 3/2 | 8.8 | 83% | 83% | 61% |
| 4/3 | 12.8 | 87% | 85% | 60% |
| 5/4 | 16.7 | 89% | 86% | 59% |
| 6/6 | 23.6 | 91% | 89% | 57% |

Same verdict per part, by task:

| Task | 3/2 | 4/3 | 5/4 | 6/6 |
|---|---|---|---|---|
| explain_to_kid | 73% | 79% | 78% | 79% |
| faq_only | 85% | 84% | 86% | 84% |
| job_extraction | 93% | 96% | 95% | 96% |
| landlord_reply | 70% | 75% | 80% | 86% |
| meeting_summary | 86% | 91% | 91% | 95% |
| privacy_bug_report | 81% | 84% | 91% | 94% |
| shopping_list | 90% | 94% | 93% | 94% |
| subject_line | 89% | 95% | 95% | 99% |
