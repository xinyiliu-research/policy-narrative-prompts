# Policy vs. narrative framing: prompts, automated checks and generated scenarios

This repo holds the prompt suite used to make matched climate-dilemma stimuli in two formats, and to administer them to LLM respondents:

- **V1 Policy.** A shared opening that names a public institution, then *Policy A* and *Policy B*. It ends before a decision is made.
- **V2 Narrative.** Two self-contained short stories, *Scenario A* and *Scenario B*. They carry the same facts as the policy case, written as hypothetical paths being carried out.

Each A/B pair contrasts two of Schwartz's seven cultural value orientations. Seven orientations give 21 pairs, and there are 3 cases per pair, so 63 cases in all.

## Layout

```
prompts/                         exact prompt texts used by the pipeline (the 63-case runs)
  policy_generation.txt          V1: generates a policy case for an assigned value pair (system prompt)
  narrative_generation.txt       V2: renders a policy case as two matched stories (system prompt)
  policy_evaluation.txt          automated check: 11 quality checks + blind value classification, policy text
  narrative_evaluation.txt       automated check: same, with a narrative-specific "format" check
  cross_format_fidelity.txt      automated check: 6 checks that policy and narrative facts match
  value_definitions.txt          Schwartz cultural value definitions shared by all prompts
  policy_administration.txt      respondent template, policy ("Which policy would you recommend?")
  narrative_administration.txt   respondent template, narrative ("Which scenario is preferable?")
  administration_variants/       question wordings used across runs (see below)
pipeline/
  run_pilot.py                   API calls, caching, mechanical checks, screening, fidelity, administration
  run_full.py                    63-case generator with revision loop, pair-diversity check, administration
  verify_outputs.py              post-run integrity checks (counts, hashes, A/B recoding, secret scan)
  prepare_prompts_1025.py        script that originally assembled the prompt texts (historical; hardcoded paths)
  render_administration_prompts.py  rebuilds rendered_prompts/ and checks them against logged request hashes
  manifest.full63.json           run manifest: models, settings, prompt hashes, frozen bank hash, limitations
scenarios/
  scenario_bank_full63.json      the 63 generated cases: texts, researcher metadata, all screens, revision history
  scenario_bank_full63_option_wording.json  same bank with "Policy" relabelled "Option" (30 Oct run)
  scenarios_full63.csv           participant-facing texts + check results, one row per case
rendered_prompts/
  administration_prompts.{json,csv}  every filled-in respondent prompt (4 wordings x 63 cases x 2 orders)
  hash_check_summary.json        how many rendered prompts match the SHA-256 logged in each run
docs/                            reviewed Word versions of the V1/V2 generation and evaluation prompts
```

## Pipeline

1. **Generate policy (V1).** `policy_generation` gets the assigned value pair and the case's A/B mapping, plus the earlier cases for the same pair so the three cases differ.
2. **Mechanical check (code, `run_pilot.mechanical`).** Required fields are present. Title is 3–8 words, opening 80–120, each option 20–45. A/B length ratio is at most 1.30. Researcher fields are complete. The intended A/B mapping is preserved. Status-quo tags are valid, and any difference between them is explained.
3. **Blind screen (LLM, `policy_evaluation`).** The reviewer sees only the participant-facing text and the question, with no intended values. It returns PASS/FLAG with evidence for climate_centrality, shared_goal, consequences, plausibility, dominance, third_option, status_quo, global_comprehension, readability, balance and format. It also classifies each side's primary value. A case is flagged if any check flags, or if a classified value differs from the intended one or is not CLEAR.
4. **Revise once** on flags. Then render the narrative (V2) from the participant-facing policy text only.
5. **Narrative screen + cross-format fidelity.** `narrative_evaluation` runs on the stories. `cross_format_fidelity` checks actors_groups, actions_mechanisms, goals_effectiveness, gains_sacrifices, quantities_costs_timing and uncertainty_constraints. One targeted correction is allowed.
6. **Pair diversity (LLM, prompt inline in `run_full.py`).** The three cases for each pair must differ in mechanism, setting and decision.
7. **Freeze.** The bank's SHA-256 goes into the manifest. Administration refuses to run if the bank has changed.
8. **Administer.** Each prompt goes to each respondent model in a fresh context with no system prompt. Choices in B/A order are recoded to the original A/B.

Automated PASS is not human validation (`human_validated: false` throughout). In the final bank all 63 cases are `screened_comparison_eligible`.

## Question wording across runs

| File | Question | Run | Orders |
|---|---|---|---|
| `policy_recommend_20261025.txt` | Policy A/B — "Which policy would you recommend, A or B?" | 63-case table run, 25 Oct | AB + BA |
| `policy_preferable_20261026.txt` | Policy A/B — "Which policy is preferable, A or B?" | five-run "preferable", 26 Oct | AB |
| `option_preferable_20261030.txt` | Option A/B — "Which option is preferable, A or B?" | option-wording test, 30 Oct | AB |
| `narrative_preferable.txt` | Scenario A/B — "Which scenario is preferable, A or B?" | all runs | AB (+BA on 25 Oct) |

`hash_check_summary.json` shows that every rendered prompt that was administered matches its logged request hash: 126/126 for the 25 Oct run, and 63/63 for each AB-only condition. The other 63 B/A prompts in each AB-only condition are included for completeness and marked `not_administered`.

Note that format, text length and question wording change together between V1 and V2. Their separate effects cannot be isolated from these materials alone.

## Running

The scripts expect to run from a self-contained run directory holding `prompts/`, `manifest.json` and the scripts. API calls go through OpenRouter. The key is read from `~/.config/global-llm/openrouter.env` (`OPENROUTER_API_KEY=...`) and is never written to outputs. Calls are cached under `calls/`, and the scripts refuse to resend a changed request under the same ID.

```bash
mkdir -p runs/my_run && cp pipeline/*.py runs/my_run/ && cp -r prompts runs/my_run/
cp pipeline/manifest.full63.json runs/my_run/manifest.json   # then edit models, version and budget; remove the frozen hash fields
cd runs/my_run && python3 run_full.py generate && python3 run_full.py administer && python3 verify_outputs.py
```

`calls/` and `runs/` are git-ignored. Raw API logs and responses stay in the original project folder (`scenario_benchmark/erik_pipeline/`).
