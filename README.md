# Policy vs. narrative framing of climate value dilemmas

Prompts, automated checks, pipeline code and generated scenarios for presenting the same climate value dilemma to LLM respondents in two formats:

- **Policy.** A shared opening names a public institution and the climate problem, then gives *Option A* and *Option B*. The question is "Which option is preferable, A or B?"
- **Narrative.** Two self-contained short stories, *Scenario A* and *Scenario B*, carry the same facts as hypothetical paths being carried out. The question is "Which scenario is preferable, A or B?"

Each A/B pair contrasts two of Schwartz's seven cultural value orientations: Harmony, Embeddedness, Hierarchy, Mastery, Affective Autonomy, Intellectual Autonomy and Egalitarianism. All 21 value pairs are covered, with 3 cases per pair, for 63 cases.

## Contents

```
prompts/
  policy_generation.txt         generates a policy case for an assigned value pair (system prompt)
  narrative_generation.txt      renders a policy case as two matched stories (system prompt)
  policy_evaluation.txt         automated check of policy text: 11 quality checks + blind value classification
  narrative_evaluation.txt      automated check of narrative text: same checks, narrative-specific format check
  cross_format_fidelity.txt     automated check that both formats carry the same material facts (6 checks)
  value_definitions.txt         Schwartz cultural value definitions used throughout
  policy_administration.txt     respondent prompt, policy format
  narrative_administration.txt  respondent prompt, narrative format
pipeline/
  common.py                     configuration, cached API calls, mechanical checks, LLM screens
  generate.py                   builds and checks the scenario bank, then freezes it
  administer.py                 collects respondent choices
  verify.py                     integrity checks for a completed run
  render_prompts.py             writes rendered_prompts/ from the scenario bank
scenarios/
  scenario_bank.json            63 cases: texts, researcher record, all check results
  scenarios.csv                 participant-facing texts and check results, one row per case
rendered_prompts/
  administration_prompts.{json,csv}   the exact respondent prompt for each case and format (126)
config.json                     models, providers, sampling settings, value-pair assignments, prompt and bank hashes
```

## How a case is built

1. **Policy generation.** `policy_generation` receives the assigned value pair, the A/B mapping and the earlier cases for the same pair, so the three cases differ. It returns participant text plus a researcher record (intended values, mechanisms, gains, sacrifices, shared goal, horizon, costs, status-quo tags).
2. **Mechanical check** (`common.mechanical`). Required fields are present. Title is 3–8 words, opening 80–120, each option 20–45, each story 80–120. The A/B length ratio is at most 1.30. The researcher record is complete, the intended A/B mapping is preserved, and status-quo tags are valid, with any difference explained.
3. **Blind screen** (`policy_evaluation`). The reviewer sees only the participant text and the question, never the intended values. It returns PASS/FLAG with quoted evidence for climate_centrality, shared_goal, consequences, plausibility, dominance, third_option, status_quo, global_comprehension, readability, balance and format. It also classifies the value each option expresses. A text is flagged if any check flags, or if a classified value differs from the intended one or is not CLEAR. A flagged case gets one targeted revision.
4. **Narrative rendering.** `narrative_generation` sees only the participant-facing policy text. It is screened with `narrative_evaluation` and compared with the policy case using `cross_format_fidelity`: actors_groups, actions_mechanisms, goals_effectiveness, gains_sacrifices, quantities_costs_timing and uncertainty_constraints. Flags get one targeted correction.
5. **Pair diversity.** The three cases for each pair are reviewed together. They must differ in climate mechanism, setting and decision.
6. **Freeze.** The bank's SHA-256 is recorded. Administration refuses to run on a changed bank.

A case is eligible when both formats pass and fidelity and diversity pass. All 63 shipped cases are eligible. An automated PASS is not human validation (`human_validated: false`).

## Administration

Each case is shown in both formats to each respondent model in a fresh context, with no system prompt, five times. That is 63 × 2 × 4 × 5 = 2,520 responses. Models are pinned to a single provider with no fallbacks and use low reasoning effort. Temperature is set per model in `config.json` and omitted where the model's default is used. Each response is JSON `{"choice": "A|B", "reason": "30-60 words"}`, and the chosen side is mapped to its intended value.

## Running

Requires Python 3.9+ and an OpenRouter key, set as `OPENROUTER_API_KEY` or stored in `~/.config/global-llm/openrouter.env`. Outputs go to `RUN_DIR` (default `runs/default`, git-ignored). Every request and response is cached under `RUN_DIR/calls/`, so an interrupted run resumes without resending completed calls.

```bash
# Administer the shipped scenarios
RUN_DIR=runs/my_run python3 pipeline/administer.py --bank scenarios/scenario_bank.json
RUN_DIR=runs/my_run python3 pipeline/verify.py --bank scenarios/scenario_bank.json

# Or generate a new bank first, then administer and verify it
RUN_DIR=runs/new_bank python3 pipeline/generate.py
RUN_DIR=runs/new_bank python3 pipeline/administer.py
RUN_DIR=runs/new_bank python3 pipeline/verify.py
```

The scripts check prompt files against `config.json` before running. If you edit a prompt, update its hash in `prompt_hashes`.

## Notes

The two formats differ together in presentation, text length and question wording. A difference in choices reflects that combined change, not any single element. Repeated responses from one model are not independent participants.
