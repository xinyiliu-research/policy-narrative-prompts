"""Generate the scenario bank: a policy case per assigned value pair, its matched narrative pair, and all checks.

Usage: RUN_DIR=runs/my_run python3 pipeline/generate.py
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib, json
import common as C

DIVERSITY = '''Review three fictional climate cases as a set. Assess whether they are substantively different in climate mechanism, concrete setting and decision, rather than paraphrases or changed names/numbers. Different facts within the same broad domain can count; a case need not use a wholly different policy domain. Do not rate values or choose options. Return JSON {"result":"PASS|FLAG","evidence":"specific comparison","overlapping_case_ids":[]} .'''
GEN = C.CONFIG['generator_model']
TOKENS = C.CONFIG['generation_max_tokens']


def generate_case(case, previous):
    cid = case['id']
    folder = C.OUT / 'cases' / cid
    if (folder / 'record.json').exists():
        return json.loads((folder / 'record.json').read_text())
    history = []

    # 1. Policy case for the assigned value pair, then a blind screen and at most one revision.
    base = ('Create ONE new case for the assigned pair. The three cases for this pair must involve different climate '
            'mechanisms, affected settings, and substantive decisions, not merely different names or numbers. Choose an '
            'inherently climate-related dilemma. Do not reuse an earlier case listed below. Preserve the assigned A/B '
            'orientation mapping.\nASSIGNMENT:\n' + json.dumps(case) + '\nEARLIER CASES FOR THIS PAIR:\n' + json.dumps(previous))
    a = C.call(cid + '/policy_0', GEN, C.prompt('policy_generation'), base, TOKENS)
    if any(not isinstance(a.get(k), str) or not a[k].strip() for k in ['title', 'opening', 'a', 'b']):
        a = C.call(cid + '/policy_schema', GEN, C.prompt('policy_generation'),
                   base + '\nCorrect missing required fields in this draft:\n' + json.dumps(a), TOKENS)
    sa = C.screen('policy', a, cid + '/policy_screen_0')
    flags = C.quality_flags('policy', a, case, sa)
    history.append({'stage': 'policy_0', 'flags': flags})
    if flags:
        a = C.call(cid + '/policy_1', GEN, C.prompt('policy_generation'),
                   base + '\nCURRENT DRAFT:\n' + json.dumps(a) + '\nQUALITY FEEDBACK:\n' + json.dumps(flags) +
                   '\nMake one targeted revision to correct genuine problems. Retain the assigned values and climate setting. '
                   'You may clarify substantive constraints or consequences where necessary, but do not invent implausible '
                   'restrictions, inflate harms, or add a moral slogan just to pass. Preserve a credible benefit and sacrifice '
                   'on each side. Use familiar eighth-grade wording and count words. Return the complete JSON.', TOKENS)
        sa = C.screen('policy', a, cid + '/policy_screen_1')
        flags = C.quality_flags('policy', a, case, sa)
        history.append({'stage': 'policy_1', 'flags': flags})

    # 2. Narrative pair rendered from the participant-facing policy text only; screen, fidelity, at most one correction.
    source = json.dumps(C.facing(a, 'policy'), ensure_ascii=False)
    b = C.call(cid + '/narrative_0', GEN, C.prompt('narrative_generation'),
               'SOURCE CASE:\n' + source + '\nRender two self-contained stories. Retain estimated costs as estimates and all '
               'material sacrifices. The hypothetical story may describe a path being carried out even though the policy '
               'opening ends before a decision. Count 80-120 words per story.', TOKENS)
    if any(not isinstance(b.get(k), str) or not b[k].strip() for k in ['title', 'a', 'b']):
        b = C.call(cid + '/narrative_schema', GEN, C.prompt('narrative_generation'),
                   'SOURCE:\n' + source + '\nCorrect missing required fields:\n' + json.dumps(b), TOKENS)
    sb = C.screen('narrative', b, cid + '/narrative_screen_0')
    f = C.fidelity(a, b, cid + '/fidelity_0')
    nf, ff = C.quality_flags('narrative', b, case, sb), C.fidelity_flags(f)
    history.append({'stage': 'narrative_0', 'flags': nf, 'fidelity_flags': ff})
    if nf or ff:
        b = C.call(cid + '/narrative_1', GEN, C.prompt('narrative_generation'),
                   'SOURCE CASE:\n' + source + '\nCURRENT STORIES:\n' + json.dumps(b) + '\nQUALITY FEEDBACK:\n' + json.dumps(nf) +
                   '\nFIDELITY FEEDBACK:\n' + json.dumps(ff) + '\nMake one targeted correction. The source is now fixed: do not '
                   'invent or change substantive facts to appease the reviewer. Retain the 80-120 word limits and all material '
                   'facts. Recast the pending decision as hypothetical actions, not as a statement that no decision is made. '
                   'Preserve estimates and uncertainty. If a source flaw prevents a correction, record that limit in adaptation_notes.', TOKENS)
        sb = C.screen('narrative', b, cid + '/narrative_screen_1')
        f = C.fidelity(a, b, cid + '/fidelity_1')
        nf, ff = C.quality_flags('narrative', b, case, sb), C.fidelity_flags(f)
        history.append({'stage': 'narrative_1', 'flags': nf, 'fidelity_flags': ff})

    rec = {'case': case, 'policy': a, 'narrative': b, 'screens': {'policy': sa, 'narrative': sb}, 'fidelity': f,
           'history': history,
           'mechanical': {'policy': C.mechanical(a, 'policy', case), 'narrative': C.mechanical(b, 'narrative')},
           'status': {'policy': {'status': 'FLAG' if flags else 'PASS', 'reasons': flags},
                      'narrative': {'status': 'FLAG' if nf else 'PASS', 'reasons': nf}},
           'matched_fidelity': 'FLAG' if ff else 'PASS',
           'comparison_eligible': not flags and not nf and not ff,
           'human_validated': False}
    C.dump(folder / 'record.json', rec)
    print(json.dumps({'case': cid, 'policy': rec['status']['policy']['status'],
                      'narrative': rec['status']['narrative']['status'], 'fidelity': rec['matched_fidelity']}), flush=True)
    return rec


def pair_work(pid):
    """Generate the three cases of one value pair in sequence, then check that they differ."""
    previous, results = [], []
    for case in [c for c in C.CONFIG['cases'] if c['pair_id'] == pid]:
        rec = generate_case(case, previous)
        results.append(rec)
        previous.append({'case_id': case['id'], **C.facing(rec['policy'], 'policy')})
    d = C.call(pid + '/diversity', C.CONFIG['screening_model'], DIVERSITY, json.dumps(previous), 1800)
    if d.get('result') not in ['PASS', 'FLAG'] or not d.get('evidence'):
        raise ValueError('Invalid diversity review')
    for rec in results:
        rec['diversity'] = d
        rec['screened_comparison_eligible'] = rec['comparison_eligible'] and d['result'] == 'PASS'
        C.dump(C.OUT / 'cases' / rec['case']['id'] / 'record.json', rec)
    return results


def main():
    C.check_prompt_hashes()
    errors = []
    with ThreadPoolExecutor(max_workers=C.CONFIG['max_workers_generation']) as pool:
        jobs = {pool.submit(pair_work, pid): pid for pid in C.CONFIG['pairs']}
        for f in as_completed(jobs):
            try:
                f.result()
            except Exception as e:
                errors.append({'pair': jobs[f], 'error': type(e).__name__, 'detail': str(e)[:250]})
    bank = [json.loads(p.read_text()) for p in sorted((C.OUT / 'cases').glob('*/record.json'))]
    C.dump(C.OUT / 'scenario_bank.json', bank)
    C.dump(C.OUT / 'generation_errors.json', errors)
    n = len(C.CONFIG['cases'])
    if len(bank) != n or errors:
        raise RuntimeError('Generation incomplete; inspect generation_errors.json and rerun to resume')
    signatures = {C.sha256(json.dumps(C.facing(r['policy'], 'policy'), sort_keys=True)) for r in bank}
    assert len(signatures) == n, 'Exact duplicate policy cases'
    # Freeze the bank: administer.py refuses to run if it changes afterwards.
    C.dump(C.OUT / 'frozen.json', {'frozen_utc': C.now(), 'scenario_bank_sha256': C.sha256((C.OUT / 'scenario_bank.json').read_bytes())})
    print('FROZEN ' + json.dumps({'cases': n, 'eligible': sum(r['screened_comparison_eligible'] for r in bank),
                                  'cost_usd': C.cost()}), flush=True)


if __name__ == '__main__':
    main()
