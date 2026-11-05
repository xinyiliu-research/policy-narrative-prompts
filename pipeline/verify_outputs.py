from pathlib import Path
import json,hashlib,collections,csv,re
ROOT=Path(__file__).resolve().parent
M=json.loads((ROOT/'manifest.json').read_text());B=json.loads((ROOT/'scenario_bank.json').read_text());R=json.loads((ROOT/'responses.json').read_text())
assert len(B)==63 and len({r['case']['id'] for r in B})==63
assert collections.Counter(r['case']['pair_id'] for r in B)=={p:3 for p in M['pairs']}
assert hashlib.sha256((ROOT/'scenario_bank.json').read_bytes()).hexdigest()==M['frozen_bank_sha256']
for p in (ROOT/'prompts').glob('*.txt'):
 if p.stem in M['prompt_hashes']:assert hashlib.sha256(p.read_bytes()).hexdigest()==M['prompt_hashes'][p.stem]
assert len(R)==504
keys=[(r['case_id'],r['model'],r['format'],r['order']) for r in R];assert len(set(keys))==504
bank={r['case']['id']:r for r in B}
for r in R:
 c=bank[r['case_id']]['case']
 assert r['canonical_choice']==(r['displayed_choice'] if r['order']=='AB' else ('B' if r['displayed_choice']=='A' else 'A'))
 assert r['intended_value_selected']==c['orientation_'+r['canonical_choice'].lower()]
for rec in B:
 for fmt in ['policy','narrative']:
  for order in ['AB','BA']:
   a=[r for r in R if r['case_id']==rec['case']['id'] and r['format']==fmt and r['order']==order]
   assert len(a)==2 and a[0]['request_sha256']==a[1]['request_sha256']
models=collections.Counter();incomplete=[];started=[];completed=[]
for p in (ROOT/'calls').glob('**/metadata.json'):
 m=json.loads(p.read_text());
 if m.get('status')=='complete':models[(m.get('returned_model'),m.get('provider'))]+=1
 else:incomplete.append(str(p.parent.relative_to(ROOT)))
 if '/choices/' in str(p):started.append(m['started_utc'])
 if m.get('completed_utc'):completed.append(m['completed_utc'])
assert min(started)>=M['stimuli_frozen_utc']
for p in ROOT.rglob('*'):
 if p.is_file() and p.suffix in ['.txt','.json','.csv','.html','.py']:
  assert not re.search(r'sk-or-v1-[0-9a-f]{20,}',p.read_text(errors='ignore')),'Possible secret in '+str(p)
out={'cases':63,'cases_per_pair':3,'pairs':21,'response_cells':504,'unique_cells':504,'cross_model_input_hashes_match':True,'option_order_recoding_verified':True,'frozen_before_choices':True,'prompt_hashes_verified':True,'bank_hash_verified':True,'returned_models_and_providers':[{'model':k[0],'provider':k[1],'calls':v} for k,v in models.items()],'incomplete_api_attempts_retained':incomplete,'explanation_word_count_range':[min(r['reason_word_count'] for r in R),max(r['reason_word_count'] for r in R)],'human_validated':False,'secret_scan':'clear'}
(ROOT/'verification.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
