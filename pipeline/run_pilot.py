from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import json,re,urllib.request,urllib.error,datetime,hashlib,threading,sys,csv

ROOT=Path(__file__).resolve().parent
P=ROOT/'prompts'; M=json.loads((ROOT/'manifest.json').read_text())
GEN=M['generator_model']; REVIEW=M['screening_model']; LOCK=threading.Lock()
def dump(p,x): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def prompt(name): return (P/(name+'.txt')).read_text()
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def credential():
 for line in (Path.home()/'.config/global-llm/openrouter.env').read_text().splitlines():
  m=re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',line)
  if m:return m[1].strip().strip('\"\'')
 raise RuntimeError('Saved credential missing')
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d: raise ValueError('Duplicate JSON key '+k)
  d[k]=v
 return d
def cost():
 return sum(json.loads(p.read_text()).get('usage',{}).get('cost',0) or 0 for p in (ROOT/'calls').glob('**/response.json'))
def call(tag,model,system,user,tokens):
 folder=ROOT/'calls'/tag; folder.mkdir(parents=True,exist_ok=True)
 messages=([{'role':'system','content':system}] if system else [])+[{'role':'user','content':user}]
 payload={'model':model,'messages':messages,'max_tokens':tokens,'reasoning':{'effort':'low'},'response_format':{'type':'json_object'},'provider':{'allow_fallbacks':False,'require_parameters':True}}
 if (folder/'parsed.json').exists():
  if json.loads((folder/'request.json').read_text())!=payload:raise ValueError('Cached request mismatch '+tag)
  return json.loads((folder/'parsed.json').read_text())
 if (folder/'request.json').exists():raise RuntimeError('Unresolved prior call; not automatically resent: '+tag)
 with LOCK:
  if cost()>=M['budget_cap_usd']:raise RuntimeError('Budget cap reached')
  dump(folder/'request.json',payload)
 meta={'started_utc':now(),'requested_model':model}; dump(folder/'metadata.json',meta)
 key=credential()
 try:
  req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=420) as r: response=json.load(r)
  dump(folder/'response.json',response)
  choice=response['choices'][0]
  if choice['finish_reason']!='stop':raise ValueError('Incomplete API response: '+str(choice['finish_reason']))
  raw=choice['message']['content']; (folder/'raw.txt').write_text(raw)
  parsed=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip()),object_pairs_hook=unique)
  if not isinstance(parsed,dict):raise ValueError('Expected object')
  dump(folder/'parsed.json',parsed)
  meta.update(status='complete',returned_model=response.get('model'),provider=response.get('provider'),response_id=response.get('id'),usage=response.get('usage'),completed_utc=now())
  dump(folder/'metadata.json',meta)
  return parsed
 except Exception as e:
  meta.update(status='incomplete',error_type=type(e).__name__,detail=str(e).replace(key,'[REDACTED]')[:300]);dump(folder/'metadata.json',meta);raise
def wc(t):return len(t.split())
def mechanical(x,fmt,case=None):
 errors=[]; fields=['title','a','b']+(['opening'] if fmt=='policy' else [])
 for k in fields:
  if not isinstance(x.get(k),str) or not x[k].strip():errors.append('Missing string '+k)
 if errors:return errors
 if not 3<=wc(x['title'])<=8:errors.append('Title must have 3-8 words')
 limits={'opening':(80,120),'a':(20,45),'b':(20,45)} if fmt=='policy' else {'a':(80,120),'b':(80,120)}
 for k,(lo,hi) in limits.items():
  if not lo<=wc(x[k])<=hi:errors.append(f'{k} has {wc(x[k])} words; requires {lo}-{hi}')
 if max(wc(x['a']),wc(x['b']))/min(wc(x['a']),wc(x['b']))>1.3:errors.append('A/B length ratio exceeds 1.30')
 if fmt=='policy':
  r=x.get('researcher',{})
  for k in ['orientation_a','orientation_b','mechanism_a','mechanism_b','gain_a','gain_b','sacrifice_a','sacrifice_b','shared_goal','expected_success','horizon','costs','affected_groups','status_quo_a','status_quo_b']:
   if not isinstance(r.get(k),str) or not r[k].strip():errors.append('Missing researcher field '+k)
  for side in ['a','b']:
   if r.get('orientation_'+side)!=case['orientation_'+side]:errors.append('Intended mapping mismatch '+side)
   if r.get('status_quo_'+side) not in ['NEW','INCREMENTAL','STATUS_QUO']:errors.append('Invalid status quo tag')
  if r.get('status_quo_a')!=r.get('status_quo_b') and not r.get('status_quo_exception','').strip():errors.append('Missing status quo exception')
  if not isinstance(r.get('limitations'),list):errors.append('Missing limitations list')
 elif not isinstance(x.get('adaptation_notes'),list):errors.append('Missing adaptation_notes list')
 return errors
def facing(x,fmt):return {k:x[k] for k in (['title','opening','a','b'] if fmt=='policy' else ['title','a','b'])}
def validate_checks(x,keys):
 if set(x.get('checks',{}))!=set(keys):raise ValueError('Checker keys incomplete')
 for v in x['checks'].values():
  if v.get('result') not in ['PASS','FLAG'] or not v.get('evidence','').strip():raise ValueError('Invalid check result')
def screen(fmt,x,tag):
 question='Which policy would you recommend, A or B?' if fmt=='policy' else 'Which scenario is preferable, A or B?'
 q=call(tag,REVIEW,prompt(fmt+'_evaluation'),json.dumps({'text':facing(x,fmt),'question':question},ensure_ascii=False),4000)
 validate_checks(q,M['quality_keys'])
 allowed=['Harmony','Embeddedness','Hierarchy','Mastery','Affective Autonomy','Intellectual Autonomy','Egalitarianism']
 for side in ['a','b']:
  c=q['classification'][side]
  if c.get('primary') not in allowed+['UNCLEAR'] or c.get('secondary') not in allowed+['NONE'] or c.get('ambiguity') not in ['CLEAR','BORDERLINE','UNCLEAR'] or not c.get('evidence'):raise ValueError('Invalid classification')
 return q
def fidelity(a,b,tag):
 q=call(tag,REVIEW,prompt('cross_format_fidelity'),json.dumps({'policy':facing(a,'policy'),'narrative':facing(b,'narrative')},ensure_ascii=False),3500)
 validate_checks(q,M['fidelity_keys']);return q
def generate_case(case):
 cid=case['id']; folder=ROOT/'cases'/cid
 base='Create one new case for this assignment. All example settings are open; do not force a nature/technology contrast.\n'+json.dumps(case)
 a=call(cid+'/policy_generation_0',GEN,prompt('policy_generation'),base,4500)
 err=mechanical(a,'policy',case)
 if err:
  a=call(cid+'/policy_generation_1',GEN,prompt('policy_generation'),base+'\nCorrect only these format/schema errors and preserve the substance:\n'+json.dumps(err)+'\nDraft:\n'+json.dumps(a),4500)
 dump(folder/'policy.json',a)
 source=json.dumps(facing(a,'policy'),ensure_ascii=False)
 b=call(cid+'/narrative_generation_0',GEN,prompt('narrative_generation'),'SOURCE CASE:\n'+source,4500)
 err=mechanical(b,'narrative')
 if err:
  b=call(cid+'/narrative_generation_1',GEN,prompt('narrative_generation'),'SOURCE CASE:\n'+source+'\nCorrect these format errors without changing source content:\n'+json.dumps(err)+'\nDraft:\n'+json.dumps(b),4500)
 f=fidelity(a,b,cid+'/fidelity_0')
 if any(v['result']=='FLAG' for v in f['checks'].values()):
  b=call(cid+'/narrative_fidelity_repair',GEN,prompt('narrative_generation'),'SOURCE CASE:\n'+source+'\nCURRENT NARRATIVE:\n'+json.dumps(b)+'\nFidelity feedback from a fallible reviewer. Correct actual omissions or changes; do not change source facts or invent details. Keep each story at 80-120 words:\n'+json.dumps(f),4500)
  f=fidelity(a,b,cid+'/fidelity_final')
 dump(folder/'narrative.json',b);dump(folder/'fidelity.json',f)
 # Blind screens do not receive assigned pairs, generation explanations, or each other's results.
 sa=screen('policy',a,cid+'/policy_screen');sb=screen('narrative',b,cid+'/narrative_screen')
 dump(folder/'policy_screen.json',sa);dump(folder/'narrative_screen.json',sb)
 record={'case':case,'policy':a,'narrative':b,'fidelity':f,'screens':{'policy':sa,'narrative':sb},'mechanical':{'policy':mechanical(a,'policy',case),'narrative':mechanical(b,'narrative')}}
 record['status']={}
 for fmt,s in [('policy',sa),('narrative',sb)]:
  flags=list(record['mechanical'][fmt])+[k+': '+v['evidence'] for k,v in s['checks'].items() if v['result']=='FLAG']
  for side in ['a','b']:
   c=s['classification'][side]
   if c['primary']!=case['orientation_'+side] or c['ambiguity']!='CLEAR':flags.append('Value '+side.upper()+': '+c['primary']+' / '+c['ambiguity']+'; intended '+case['orientation_'+side])
  record['status'][fmt]={'status':'FLAG' if flags else 'PASS','reasons':flags,'human_validated':False}
 record['matched_fidelity']='PASS' if all(v['result']=='PASS' for v in f['checks'].values()) else 'FLAG'
 record['comparison_eligible']=record['matched_fidelity']=='PASS' and all(v['status']=='PASS' for v in record['status'].values())
 dump(folder/'record.json',record)
 print(json.dumps({'case':cid,'status':record['status'],'fidelity':record['matched_fidelity']}),flush=True)
 return record
def generate():
 results=[];errors=[]
 with ThreadPoolExecutor(max_workers=3) as pool:
  jobs={pool.submit(generate_case,c):c['id'] for c in M['cases']}
  for f in as_completed(jobs):
   try:results.append(f.result())
   except Exception as e:errors.append({'case':jobs[f],'error':type(e).__name__,'detail':str(e)[:250]});print(json.dumps(errors[-1]),flush=True)
 results.sort(key=lambda r:r['case']['id']);dump(ROOT/'scenario_bank.json',results);dump(ROOT/'generation_errors.json',errors)
 print('GENERATION_DONE '+json.dumps({'cases':len(results),'errors':len(errors),'cost_usd':cost()}),flush=True)
def administer_one(record,fmt,model,order):
 cid=record['case']['id'];x=facing(record[fmt],fmt)
 if order=='BA':x['a'],x['b']=x['b'],x['a']
 user=prompt(fmt+'_administration').format(**x)
 short='gpt' if model.startswith('openai/') else 'deepseek'
 ans=call(f'choices/{short}/{cid}/{fmt}/{order}',model,'',user,1600)
 if ans.get('choice') not in ['A','B'] or not isinstance(ans.get('reason'),str) or not ans['reason'].strip():raise ValueError('Invalid choice response')
 shown=ans['choice'];canonical=shown if order=='AB' else ('B' if shown=='A' else 'A')
 return {'case_id':cid,'format':fmt,'model':model,'order':order,'displayed_choice':shown,'canonical_choice':canonical,'intended_value_selected':record['case']['orientation_'+canonical.lower()],'reason':ans['reason'],'reason_word_count':wc(ans['reason']),'comparison_eligible':record['comparison_eligible'],'stimulus_status':record['status'][fmt]['status'],'request_sha256':hashlib.sha256(user.encode()).hexdigest()}
def administer():
 if hashlib.sha256((ROOT/'scenario_bank.json').read_bytes()).hexdigest()!=M.get('frozen_bank_sha256'):
  raise RuntimeError('Stimulus bank differs from frozen manifest')
 bank=json.loads((ROOT/'scenario_bank.json').read_text());out=[];errors=[]
 jobspec=[(r,fmt,m,o) for r in bank for fmt in ['policy','narrative'] for m in M['respondent_models'] for o in ['AB','BA']]
 # A fixed shuffled schedule reduces systematic run-order differences; every call has a fresh context.
 import random
 random.Random(1025).shuffle(jobspec)
 dump(ROOT/'administration_schedule.json',[{'case_id':r['case']['id'],'format':f,'model':m,'order':o} for r,f,m,o in jobspec])
 with ThreadPoolExecutor(max_workers=4) as pool:
  jobs={pool.submit(administer_one,*s):s for s in jobspec}
  for f in as_completed(jobs):
   try:out.append(f.result())
   except Exception as e:
    s=jobs[f];errors.append({'case':s[0]['case']['id'],'format':s[1],'model':s[2],'order':s[3],'error':type(e).__name__,'detail':str(e)[:250]})
   dump(ROOT/'responses.json',out);dump(ROOT/'response_errors.json',errors)
   print('CHOICES '+json.dumps({'complete':len(out),'errors':len(errors),'target':len(jobspec)}),flush=True)
 out.sort(key=lambda r:(r['case_id'],r['model'],r['format'],r['order']));dump(ROOT/'responses.json',out)
 if out:
  with (ROOT/'responses.csv').open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
 print('ADMINISTRATION_DONE '+json.dumps({'responses':len(out),'errors':len(errors),'cost_usd':cost()}),flush=True)
if __name__=='__main__':
 if sys.argv[1]=='generate':generate()
 elif sys.argv[1]=='administer':administer()
