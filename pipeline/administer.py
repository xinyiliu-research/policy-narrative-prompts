"""Administer the frozen scenarios: every case x format x respondent model x repetition, each in a fresh context.

Usage:
  RUN_DIR=runs/my_run python3 pipeline/administer.py                                    # bank made by generate.py
  RUN_DIR=runs/my_run python3 pipeline/administer.py --bank scenarios/scenario_bank.json  # shipped bank
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse, csv, json, random
import common as C


def expected_bank_hash(bank_path):
    frozen = C.OUT / 'frozen.json'
    if bank_path == C.OUT / 'scenario_bank.json' and frozen.exists():
        return json.loads(frozen.read_text())['scenario_bank_sha256']
    return C.CONFIG['scenario_bank_sha256']


def answer(rec, fmt, model, run):
    cid = rec['case']['id']
    user = C.prompt(fmt + '_administration').format(**C.facing(rec[fmt], fmt))
    tag = f"choices/{model.replace('/', '_')}/{cid}/{fmt}/run_{run}"
    a = C.call(tag, model, '', user, C.CONFIG['administration_max_tokens'], respondent=True)
    if a.get('choice') not in ['A', 'B'] or not isinstance(a.get('reason'), str) or not a['reason'].strip():
        a = C.call(tag + '/schema_retry', model, '', user, C.CONFIG['administration_max_tokens'], respondent=True)
        if a.get('choice') not in ['A', 'B'] or not a.get('reason'):
            raise ValueError('Invalid choice schema')
    return {'case_id': cid, 'pair_id': rec['case']['pair_id'], 'replicate': rec['case']['replicate'],
            'model': model, 'format': fmt, 'run': run, 'choice': a['choice'],
            'intended_value_selected': rec['case']['orientation_' + a['choice'].lower()],
            'reason': a['reason'], 'reason_word_count': C.wc(a['reason']), 'request_sha256': C.sha256(user)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bank', type=Path, default=C.OUT / 'scenario_bank.json')
    bank_path = ap.parse_args().bank.resolve()
    C.check_prompt_hashes()
    if C.sha256(bank_path.read_bytes()) != expected_bank_hash(bank_path):
        raise RuntimeError('Scenario bank differs from its frozen hash')
    bank = json.loads(bank_path.read_text())

    # A fixed shuffled schedule within each repetition block reduces systematic run-order differences.
    spec = []
    for run in range(1, C.CONFIG['repetitions'] + 1):
        block = [(r, fmt, m, run) for r in bank for fmt in ['policy', 'narrative'] for m in C.CONFIG['respondent_models']]
        random.Random(C.CONFIG['schedule_seed'] + run).shuffle(block)
        spec += block
    C.dump(C.OUT / 'administration_schedule.json',
           [{'case_id': r['case']['id'], 'format': f, 'model': m, 'run': n} for r, f, m, n in spec])

    out, errors = [], []
    with ThreadPoolExecutor(max_workers=C.CONFIG['max_workers_administration']) as pool:
        jobs = {pool.submit(answer, *s): s for s in spec}
        for i, f in enumerate(as_completed(jobs), 1):
            try:
                out.append(f.result())
            except Exception as e:
                r, fmt, m, n = jobs[f]
                errors.append({'case_id': r['case']['id'], 'format': fmt, 'model': m, 'run': n,
                               'error': type(e).__name__, 'detail': str(e)[:200]})
            if i % 250 == 0:
                print('CHOICES ' + json.dumps({'complete': len(out), 'errors': len(errors), 'target': len(spec),
                                               'cost_usd': round(C.cost(), 4)}), flush=True)
    out.sort(key=lambda r: (r['case_id'], r['model'], r['format'], r['run']))
    C.dump(C.OUT / 'responses.json', out)
    C.dump(C.OUT / 'response_errors.json', errors)
    if out:
        with (C.OUT / 'responses.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
    print('DONE ' + json.dumps({'complete': len(out), 'errors': len(errors), 'cost_usd': round(C.cost(), 4)}), flush=True)
    if errors:
        raise RuntimeError('Some cells incomplete; rerun to resume from cached calls')


if __name__ == '__main__':
    main()
