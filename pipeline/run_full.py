from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,hashlib,threading,time,sys,csv,random,collections
import run_pilot as R

ROOT=R.ROOT;M=R.M;ORIGINAL_CALL=R.call
def atomic_dump(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 t=p.with_name(p.name+'.'+str(threading.get_ident())+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');t.replace(p)
R.dump=atomic_dump
def safe_call(tag,model,system,user,tokens):
 last=None
 for attempt in range(3):
  try:return ORIGINAL_CALL(tag+f'/attempt_{attempt}',model,system,user,tokens if attempt==0 else max(tokens,6500))
  except Exception as e:
   if 'Budget cap' in str(e) or 'Cached request mismatch' in str(e):raise
   last=e
   if attempt<2:time.sleep(1+attempt)
 raise last
R.call=safe_call
def quality(fmt,x,case,review):
 flags=R.mechanical(x,fmt,case)
 flags += [k+': '+v['evidence'] for k,v in review['checks'].items() if v['result']=='FLAG']
 for side in ['a','b']:
  c=review['classification'][side]
  if c['primary']!=case['orientation_'+side] or c['ambiguity']!='CLEAR':flags.append('Value '+side+': '+c['primary']+' / '+c['ambiguity']+'; intended '+case['orientation_'+side])
 return flags
def checked(fmt,x,tag):
 try:return R.screen(fmt,x,tag)
 except (ValueError,KeyError,TypeError):return R.screen(fmt,x,tag+'_schema_retry')
def fidelity(a,b,tag):
 try:return R.fidelity(a,b,tag)
 except (ValueError,KeyError,TypeError):return R.fidelity(a,b,tag+'_schema_retry')
def generate_case(case,previous):
 cid=case['id'];folder=ROOT/'cases'/cid
 if (folder/'record.json').exists():return json.loads((folder/'record.json').read_text())
 history=[]
 base='Create ONE new case for the assigned pair. The three cases for this pair must involve different climate mechanisms, affected settings, and substantive decisions, not merely different names or numbers. Choose an inherently climate-related dilemma. Do not reuse an earlier case listed below. Preserve the assigned A/B orientation mapping.\nASSIGNMENT:\n'+json.dumps(case)+'\nEARLIER CASES FOR THIS PAIR:\n'+json.dumps(previous)
 a=R.call(cid+'/policy_0',R.GEN,R.prompt('policy_generation'),base,4500)
 # Repair missing fields before participant-text review; never infer a pass from malformed text.
 if any(k not in a or not isinstance(a[k],str) or not a[k].strip() for k in ['title','opening','a','b']):
  a=R.call(cid+'/policy_schema',R.GEN,R.prompt('policy_generation'),base+'\nCorrect missing required fields in this draft:\n'+json.dumps(a),4500)
 sa=checked('policy',a,cid+'/policy_screen_0');flags=quality('policy',a,case,sa)
 history.append({'stage':'policy_0','flags':flags})
 if flags:
  a=R.call(cid+'/policy_1',R.GEN,R.prompt('policy_generation'),base+'\nCURRENT DRAFT:\n'+json.dumps(a)+'\nQUALITY FEEDBACK:\n'+json.dumps(flags)+'\nMake one targeted revision to correct genuine problems. Retain the assigned values and climate setting. You may clarify substantive constraints or consequences where necessary, but do not invent implausible restrictions, inflate harms, or add a moral slogan just to pass. Preserve a credible benefit and sacrifice on each side. Use familiar eighth-grade wording and count words. Return the complete JSON.',4500)
  sa=checked('policy',a,cid+'/policy_screen_1');flags=quality('policy',a,case,sa);history.append({'stage':'policy_1','flags':flags})
 R.dump(folder/'policy.json',a);R.dump(folder/'policy_screen.json',sa)
 source=json.dumps(R.facing(a,'policy'),ensure_ascii=False)
 b=R.call(cid+'/narrative_0',R.GEN,R.prompt('narrative_generation'),'SOURCE CASE:\n'+source+'\nRender two self-contained stories. Retain estimated costs as estimates and all material sacrifices. The hypothetical story may describe a path being carried out even though the policy opening ends before a decision. Count 80-120 words per story.',4500)
 if any(k not in b or not isinstance(b[k],str) or not b[k].strip() for k in ['title','a','b']):
  b=R.call(cid+'/narrative_schema',R.GEN,R.prompt('narrative_generation'),'SOURCE:\n'+source+'\nCorrect missing required fields:\n'+json.dumps(b),4500)
 sb=checked('narrative',b,cid+'/narrative_screen_0');f=fidelity(a,b,cid+'/fidelity_0')
 nf=quality('narrative',b,case,sb);ff=[k+': '+v['evidence'] for k,v in f['checks'].items() if v['result']=='FLAG']
 history.append({'stage':'narrative_0','flags':nf,'fidelity_flags':ff})
 if nf or ff:
  b=R.call(cid+'/narrative_1',R.GEN,R.prompt('narrative_generation'),'SOURCE CASE:\n'+source+'\nCURRENT STORIES:\n'+json.dumps(b)+'\nQUALITY FEEDBACK:\n'+json.dumps(nf)+'\nFIDELITY FEEDBACK:\n'+json.dumps(ff)+'\nMake one targeted correction. The source is now fixed: do not invent or change substantive facts to appease the reviewer. Retain the 80-120 word limits and all material facts. Recast the pending decision as hypothetical actions, not as a statement that no decision is made. Preserve estimates and uncertainty. If a source flaw prevents a correction, record that limit in adaptation_notes.',4500)
  sb=checked('narrative',b,cid+'/narrative_screen_1');f=fidelity(a,b,cid+'/fidelity_1')
  nf=quality('narrative',b,case,sb);ff=[k+': '+v['evidence'] for k,v in f['checks'].items() if v['result']=='FLAG']
  history.append({'stage':'narrative_1','flags':nf,'fidelity_flags':ff})
 rec={'case':case,'policy':a,'narrative':b,'screens':{'policy':sa,'narrative':sb},'fidelity':f,'history':history,'mechanical':{'policy':R.mechanical(a,'policy',case),'narrative':R.mechanical(b,'narrative')},'status':{'policy':{'status':'FLAG' if flags else 'PASS','reasons':flags},'narrative':{'status':'FLAG' if nf else 'PASS','reasons':nf}},'matched_fidelity':'FLAG' if ff else 'PASS','comparison_eligible':not flags and not nf and not ff,'human_validated':False}
 for name,x in [('narrative',b),('narrative_screen',sb),('fidelity',f),('record',rec)]:R.dump(folder/(name+'.json'),x)
 print(json.dumps({'completed_case':cid,'policy':rec['status']['policy']['status'],'narrative':rec['status']['narrative']['status'],'fidelity':rec['matched_fidelity']}),flush=True)
 return rec
DIVERSITY='''Review three fictional climate cases as a set. Assess whether they are substantively different in climate mechanism, concrete setting and decision, rather than paraphrases or changed names/numbers. Different facts within the same broad domain can count; a case need not use a wholly different policy domain. Do not rate values or choose options. Return JSON {"result":"PASS|FLAG","evidence":"specific comparison","overlapping_case_ids":[]} .'''
def pair_work(pid):
 previous=[];results=[]
 for c in [c for c in M['cases'] if c['pair_id']==pid]:
  rec=generate_case(c,previous);results.append(rec)
  previous.append({'case_id':c['id'],**R.facing(rec['policy'],'policy')})
 d=R.call(pid+'/diversity',R.REVIEW,DIVERSITY,json.dumps(previous),1800)
 if d.get('result') not in ['PASS','FLAG'] or not d.get('evidence'):raise ValueError('Invalid diversity review')
 R.dump(ROOT/'pair_diversity'/f'{pid}.json',d)
 for rec in results:
  rec['diversity']=d;rec['screened_comparison_eligible']=rec['comparison_eligible'] and d['result']=='PASS'
  R.dump(ROOT/'cases'/rec['case']['id']/'record.json',rec)
 return results
def assemble():
 records=[json.loads(p.read_text()) for p in sorted((ROOT/'cases').glob('*/record.json'))]
 R.dump(ROOT/'scenario_bank.json',records)
 return records
def generate():
 errors=[]
 with ThreadPoolExecutor(max_workers=M['max_workers_generation']) as pool:
  jobs={pool.submit(pair_work,pid):pid for pid in M['pairs']}
  for f in as_completed(jobs):
   try:f.result()
   except Exception as e:errors.append({'pair':jobs[f],'error':type(e).__name__,'detail':str(e)[:250]})
   bank=assemble();R.dump(ROOT/'generation_errors.json',errors)
   R.dump(ROOT/'progress.json',{'phase':'generation','cases':len(bank),'target':63,'pairs_reviewed':len(list((ROOT/'pair_diversity').glob('*.json'))),'errors':errors,'cost_usd':R.cost()})
   print('PROGRESS '+json.dumps({'cases':len(bank),'errors':len(errors),'cost_usd':R.cost()}),flush=True)
 bank=assemble()
 if len(bank)!=63 or errors:raise RuntimeError('Generation incomplete; inspect generation_errors.json and resume')
 assert len({r['case']['id'] for r in bank})==63
 signatures=[hashlib.sha256(json.dumps(R.facing(r['policy'],'policy'),sort_keys=True).encode()).hexdigest() for r in bank]
 assert len(set(signatures))==63,'Exact duplicate policy cases'
 M['stimuli_frozen_utc']=R.now();M['frozen_bank_sha256']=hashlib.sha256((ROOT/'scenario_bank.json').read_bytes()).hexdigest();R.dump(ROOT/'manifest.json',M)
 print('GENERATION_FROZEN '+json.dumps({'cases':len(bank),'eligible':sum(r['screened_comparison_eligible'] for r in bank),'cost_usd':R.cost()}),flush=True)
def answer(rec,fmt,model,order):
 cid=rec['case']['id'];x=R.facing(rec[fmt],fmt)
 if order=='BA':x['a'],x['b']=x['b'],x['a']
 user=R.prompt(fmt+'_administration').format(**x);short='gpt' if model.startswith('openai/') else 'deepseek'
 a=R.call(f'choices/{short}/{cid}/{fmt}/{order}',model,'',user,4000)
 if a.get('choice') not in ['A','B'] or not isinstance(a.get('reason'),str) or not a['reason'].strip():
  a=R.call(f'choices/{short}/{cid}/{fmt}/{order}/schema_retry',model,'',user,4000)
  if a.get('choice') not in ['A','B'] or not a.get('reason'):raise ValueError('Invalid choice schema')
 original=a['choice'] if order=='AB' else ('B' if a['choice']=='A' else 'A')
 return {'case_id':cid,'pair_id':rec['case']['pair_id'],'replicate':rec['case']['replicate'],'model':model,'format':fmt,'order':order,'displayed_choice':a['choice'],'canonical_choice':original,'intended_value_selected':rec['case']['orientation_'+original.lower()],'reason':a['reason'],'reason_word_count':R.wc(a['reason']),'text_screen':rec['status'][fmt]['status'],'fidelity':rec['matched_fidelity'],'diversity':rec['diversity']['result'],'screened_comparison_eligible':rec['screened_comparison_eligible'],'request_sha256':hashlib.sha256(user.encode()).hexdigest()}
def administer():
 if hashlib.sha256((ROOT/'scenario_bank.json').read_bytes()).hexdigest()!=M.get('frozen_bank_sha256'):raise RuntimeError('Unfrozen or changed bank')
 bank=json.loads((ROOT/'scenario_bank.json').read_text());assert len(bank)==63
 spec=[(r,f,m,o) for r in bank for f in ['policy','narrative'] for m in M['respondent_models'] for o in ['AB','BA']];random.Random(102563).shuffle(spec)
 R.dump(ROOT/'administration_schedule.json',[{'case_id':r['case']['id'],'format':f,'model':m,'order':o} for r,f,m,o in spec])
 out=[];errors=[]
 with ThreadPoolExecutor(max_workers=M['max_workers_administration']) as pool:
  jobs={pool.submit(answer,*s):s for s in spec}
  for f in as_completed(jobs):
   try:out.append(f.result())
   except Exception as e:
    s=jobs[f];errors.append({'case':s[0]['case']['id'],'format':s[1],'model':s[2],'order':s[3],'error':type(e).__name__,'detail':str(e)[:200]})
   R.dump(ROOT/'responses.json',out);R.dump(ROOT/'response_errors.json',errors)
   if (len(out)+len(errors))%10==0:
    R.dump(ROOT/'progress.json',{'phase':'choices','complete':len(out),'target':504,'errors':errors,'cost_usd':R.cost()});print('CHOICES '+json.dumps({'complete':len(out),'errors':len(errors),'target':504,'cost_usd':R.cost()}),flush=True)
 out.sort(key=lambda r:(r['case_id'],r['model'],r['format'],r['order']));R.dump(ROOT/'responses.json',out)
 if out:
  with (ROOT/'responses.csv').open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
 print('ADMIN_DONE '+json.dumps({'complete':len(out),'errors':len(errors),'cost_usd':R.cost()}),flush=True)
 if errors:raise RuntimeError('Some response cells incomplete; inspect and resume')
if __name__=='__main__':
 if sys.argv[1]=='generate':generate()
 elif sys.argv[1]=='administer':administer()
