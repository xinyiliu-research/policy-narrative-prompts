import json,hashlib,csv,collections,sys
from pathlib import Path
SRC=Path('/Users/liuxinyi/Downloads/Projects/Global LLM/scenario_benchmark/erik_pipeline')
R=Path(__file__).resolve().parents[1]
V=R/'prompts/administration_variants'
def facing(x,fmt): return {k:x[k] for k in (['title','opening','a','b'] if fmt=='policy' else ['title','a','b'])}
def logged(run):
    p=SRC/run/'responses.json'; d=json.loads(p.read_text())
    h=collections.defaultdict(set)
    for r in d: h[(r['case_id'],r['format'],r['order'])].add(r['request_sha256'])
    return h
conds=[('policy_recommend','scenario_bank_full63.json','policy','policy_recommend_20261025.txt','framing_full63_table_20261025','policy'),
       ('policy_preferable','scenario_bank_full63.json','policy','policy_preferable_20261026.txt','framing_preferable_20261026','policy'),
       ('option_preferable','scenario_bank_full63_option_wording.json','policy','option_preferable_20261030.txt','framing_option_20261030','policy'),
       ('narrative_preferable','scenario_bank_full63.json','narrative','narrative_preferable.txt','framing_preferable_20261026','narrative')]
rows=[];summary={}
for name,bank,fmt,tpl,run,logfmt in conds:
    B=json.loads((R/'scenarios'/bank).read_text()); T=(V/tpl).read_text().rstrip('\n'); H=logged(run)
    ok=bad=missing=0
    for rec in B:
        for order in ['AB','BA']:
            x=facing(rec[fmt],fmt)
            if order=='BA': x['a'],x['b']=x['b'],x['a']
            for cand in (T,T+'\n'):
                u=cand.format(**x); h=hashlib.sha256(u.encode()).hexdigest()
                if h in H.get((rec['case']['id'],logfmt,order),()): break
            hs=H.get((rec['case']['id'],logfmt,order))
            st='match' if hs and h in hs else ('not_administered' if not hs else 'MISMATCH')
            ok+=st=='match'; bad+=st=='MISMATCH'; missing+=st=='not_administered'
            rows.append({'condition':name,'case_id':rec['case']['id'],'pair_id':rec['case']['pair_id'],'orientation_a':rec['case']['orientation_a'],'orientation_b':rec['case']['orientation_b'],'order':order,'request_sha256':h,'hash_check':st,'prompt':u})
    summary[name]={'prompts':len(B)*2,'match':ok,'mismatch':bad,'not_administered':missing,'checked_against':run+'/responses.json'}
print(json.dumps(summary,indent=1))
if '--write' in sys.argv:
    out=R/'rendered_prompts'
    json.dump(rows,open(out/'administration_prompts.json','w'),ensure_ascii=False,indent=1)
    with open(out/'administration_prompts.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    json.dump(summary,open(out/'hash_check_summary.json','w'),indent=1)
    # participant-facing scenario table
    B=json.loads((R/'scenarios/scenario_bank_full63.json').read_text())
    with open(R/'scenarios/scenarios_full63.csv','w',newline='') as f:
        w=csv.writer(f);w.writerow(['case_id','pair_id','orientation_a','orientation_b','policy_title','policy_opening','policy_a','policy_b','narrative_title','narrative_a','narrative_b','policy_screen','narrative_screen','fidelity','diversity','screened_comparison_eligible','human_validated'])
        for r in B:
            p,n=r['policy'],r['narrative']
            w.writerow([r['case']['id'],r['case']['pair_id'],r['case']['orientation_a'],r['case']['orientation_b'],p['title'],p['opening'],p['a'],p['b'],n['title'],n['a'],n['b'],r['status']['policy']['status'],r['status']['narrative']['status'],r['matched_fidelity'],r['diversity']['result'],r['screened_comparison_eligible'],r['human_validated']])
