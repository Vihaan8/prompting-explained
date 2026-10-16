# Testing with messy prompts

Real people don't write clean prompts, so I tested the tool on 32 badly written ones: typos ("inflashun", "shoping"), text-speak ("pls", "u", "thx"), all caps, run-ons with no punctuation, rambling backstory, vague asks ("not too long"), instructions that work against the goal ("make it really detailed", "make up a salary"), leading questions ("there probably is one, right?"), and off-task requests ("ignore the email and write a poem"). There are 4 per task across all 8 tasks.

Before running anything, I wrote down what I expected each of the 85 parts to do (`results/expectations_messy.yaml`). Then I ran the tool with exactly those parts and compared (`scripts/validate_expectations.py --spec results/expectations_messy.yaml`).

## Raw agreement

I agreed with the tool on 44 of 85 parts (52%, Cohen's kappa 0.21). That's much lower than the 76% on the cleaner prompt set (`results/expectations_report.md`). Full table: `results/expectations_messy_report.md`.

## Auditing the disagreements

Raw agreement only says who disagreed, not who was right. So I read the answer with and without each disputed part, and judged by what actually happened. These calls are mine, so treat them as one careful reader's view, not ground truth.

**The tool was right, or at least defensible, and my expectation was wrong: about 35 of 41.** The common reasons:

- **The AI did it anyway.**
  - On the meeting summary, "short", "only the decision stuff" and "under 60 words" back each other up. Remove any one and the summary is still short and decision-first, so each one alone looks like it doesn't matter. That's the redundancy problem with one-at-a-time removal, which Shapley values were designed to handle.
  - On the bug report, removing "make this a bug report" still produced a bug report, because the support ticket made the job obvious.
- **The AI refused a bad instruction.** "Make up a salary" came back as *ignored*: the AI said "I won't invent the salary." "and say sorry for the confusion" was ignored too.
- **Effects I didn't predict, which were real:**
  - "for github issues" made the AI write "Users report…" instead of "Marcus Lee reports…". It protected the customer's privacy without being asked to.
  - "no extra txt" kept the salary field clean. Without it, the field said "Not specified (includes $2,000 sign-on bonus)".
  - "dont guess" backfired. With it, the AI speculated *more* ("which suggests a pool"), consistently across all 5 runs.
  - "if ur not sure just say yes" made the AI answer more carefully, not less.

**Real weaknesses in the tool: about 6 of 41.**

1. **A loose "did it do the task" check.** With "Shopping list please." removed, the AI gave cooking tips. They mentioned chicken, so they passed the check. I fixed this: a shopping list now has to be at least 3 short lines that each name an ingredient.
2. **One failed check can hide another part's effect.** "(i have salt + olive oil + oregano)" did keep pantry items off the list. But the same answer also failed "no cooking steps", so the overall score didn't move. The per-check numbers under "How it works" show it; the headline verdict doesn't.
3. **Comparing with deletion, not with better wording.** "Give me 5 subject line options" shows green, because removing it leaves no instruction at all, and that does worse. Occlusion can't say "a different instruction would have been better". The privacy case ("include who reported it") is muddled the same way: the AI leaked the name with or without it.
4. **A lenient judge.** The per-part check counted "olive oil (check you have some)" as following "i have olive oil".

## Changes made because of this testing

- **A per-part noise floor.** Each part is now compared with two standard errors of its own with/without difference, never less than 0.05. Before, one floor came from the full prompt's 3 runs alone. When those happened to agree, the floor fell to 0.05 even if the shortened prompts varied a lot, which produced false reds such as "im so sorry to bother u".
- **A new blue verdict, "AI followed it".** It's for parts the AI clearly followed while the task score didn't move. Before, these showed green. For example, "ignore the email and just write a poem" was green just because the AI did write a poem.
- **An overall summary line.** It says either "Your prompt passed N of M checks", or that the AI didn't do the task at all. The poem prompt now shows as failing.
- **The shopping-list task counts plain lines as well as bullets.** A perfect four-line list with no bullet markers used to score 0.
- **Opening brackets and quotes stay with the part they open,** instead of attaching to the part before.

## Prompt splitting on messy input

I split all 32 messy prompts and 8 edge cases twice each:
- The edge cases were "?", "explain", a Spanish prompt, emoji, a code block, a repeated "hi hi hi…" prompt, a 70-word ramble, and HTML with "§" and "<".
- Every split reproduced the prompt exactly, typos and emoji included. Only "?" fell back to the regex split.
- 38 of 40 prompts split the same way both times.
- Full analyses ran without errors on "?", a one-word prompt and the 70-word ramble (9 parts, 46 calls).
