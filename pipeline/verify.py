"""Integrity checks for a run: prompt hashes, bank structure and hash, complete unique response cells, value recoding, secrets.

Usage: RUN_DIR=runs/my_run python3 pipeline/verify.py [--bank scenarios/scenario_bank.json]
"""
from pathlib import Path
import argparse, collections, json, re
import common as C

ap = argparse.ArgumentParser()
ap.add_argument('--bank', type=Path, default=C.OUT / 'scenario_bank.json')
bank_path = ap.parse_args().bank.resolve()
cfg = C.CONFIG

C.check_prompt_hashes()
bank = json.loads(bank_path.read_text())
frozen = C.OUT / 'frozen.json'
expected = json.loads(frozen.read_text())['scenario_bank_sha256'] if bank_path == C.OUT / 'scenario_bank.json' and frozen.exists() else cfg['scenario_bank_sha256']
assert C.sha256(bank_path.read_bytes()) == expected, 'Bank hash mismatch'
assert len(bank) == len(cfg['cases']) and len({r['case']['id'] for r in bank}) == len(cfg['cases'])
assert collections.Counter(r['case']['pair_id'] for r in bank) == collections.Counter(c['pair_id'] for c in cfg['cases'])

responses = json.loads((C.OUT / 'responses.json').read_text())
target = len(bank) * 2 * len(cfg['respondent_models']) * cfg['repetitions']
cells = {(r['case_id'], r['model'], r['format'], r['run']) for r in responses}
assert len(responses) == target and len(cells) == target, f'{len(responses)} responses, {len(cells)} unique; expected {target}'
by_id = {r['case']['id']: r for r in bank}
for r in responses:
    case = by_id[r['case_id']]['case']
    assert r['intended_value_selected'] == case['orientation_' + r['choice'].lower()]
    user = C.prompt(r['format'] + '_administration').format(**C.facing(by_id[r['case_id']][r['format']], r['format']))
    assert r['request_sha256'] == C.sha256(user), 'Request does not match current prompt and bank'

providers = collections.Counter()
for p in (C.OUT / 'calls').glob('**/metadata.json'):
    m = json.loads(p.read_text())
    if m.get('status') == 'complete':
        providers[(m.get('returned_model'), m.get('provider'))] += 1
for p in C.OUT.rglob('*'):
    if p.is_file() and p.suffix in ['.txt', '.json', '.csv', '.html', '.py']:
        assert not re.search(r'sk-or-v1-[0-9a-f]{20,}', p.read_text(errors='ignore')), 'Possible secret in ' + str(p)

out = {'cases': len(bank), 'response_cells': target, 'prompt_hashes_verified': True, 'bank_hash_verified': True,
       'request_hashes_verified': True, 'returned_models_and_providers': [{'model': k[0], 'provider': k[1], 'calls': v} for k, v in providers.items()],
       'human_validated': False, 'secret_scan': 'clear'}
C.dump(C.OUT / 'verification.json', out)
print(json.dumps(out, indent=2))
