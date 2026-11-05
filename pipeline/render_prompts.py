"""Write rendered_prompts/: the exact respondent prompt for every case in both formats."""
import csv, json
import common as C

bank = json.loads((C.REPO / 'scenarios' / 'scenario_bank.json').read_text())
rows = []
for rec in bank:
    for fmt in ['policy', 'narrative']:
        user = C.prompt(fmt + '_administration').format(**C.facing(rec[fmt], fmt))
        rows.append({'case_id': rec['case']['id'], 'pair_id': rec['case']['pair_id'],
                     'orientation_a': rec['case']['orientation_a'], 'orientation_b': rec['case']['orientation_b'],
                     'format': fmt, 'request_sha256': C.sha256(user), 'prompt': user})
out = C.REPO / 'rendered_prompts'
C.dump(out / 'administration_prompts.json', rows)
with (out / 'administration_prompts.csv').open('w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(len(rows), 'prompts written')
