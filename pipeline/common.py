"""Shared helpers: configuration, cached OpenRouter calls, mechanical checks and LLM screens."""
from pathlib import Path
import datetime, hashlib, json, os, re, threading, time, urllib.request

REPO = Path(__file__).resolve().parents[1]
PROMPTS = REPO / 'prompts'
CONFIG = json.loads((REPO / 'config.json').read_text())
OUT = Path(os.environ.get('RUN_DIR', REPO / 'runs' / 'default')).resolve()
CREDENTIALS = Path(os.environ.get('OPENROUTER_ENV', Path.home() / '.config/global-llm/openrouter.env'))
VALUES = ['Harmony', 'Embeddedness', 'Hierarchy', 'Mastery',
          'Affective Autonomy', 'Intellectual Autonomy', 'Egalitarianism']
QUESTION = {'policy': 'Which option is preferable, A or B?',
            'narrative': 'Which scenario is preferable, A or B?'}
LOCK = threading.Lock()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def prompt(name):
    return (PROMPTS / (name + '.txt')).read_text()


def check_prompt_hashes():
    for name, digest in CONFIG['prompt_hashes'].items():
        if sha256((PROMPTS / (name + '.txt')).read_bytes()) != digest:
            raise RuntimeError(f'Prompt {name}.txt differs from config.json prompt_hashes')


def credential():
    if os.environ.get('OPENROUTER_API_KEY'):
        return os.environ['OPENROUTER_API_KEY']
    for line in CREDENTIALS.read_text().splitlines():
        m = re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$', line)
        if m:
            return m[1].strip().strip('"\'')
    raise RuntimeError('OPENROUTER_API_KEY not found')


def cost():
    return sum(json.loads(p.read_text()).get('usage', {}).get('cost', 0) or 0
               for p in (OUT / 'calls').glob('**/response.json'))


def unique_keys(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError('Duplicate JSON key ' + k)
        d[k] = v
    return d


def _call_once(folder, payload):
    """One API request, cached in folder. A cached request must match exactly."""
    if (folder / 'parsed.json').exists():
        if json.loads((folder / 'request.json').read_text()) != payload:
            raise ValueError('Cached request mismatch ' + str(folder))
        return json.loads((folder / 'parsed.json').read_text())
    if (folder / 'request.json').exists():
        raise RuntimeError('Unresolved prior call; not automatically resent: ' + str(folder))
    with LOCK:
        if cost() >= CONFIG['budget_cap_usd']:
            raise RuntimeError('Budget cap reached')
        dump(folder / 'request.json', payload)
    meta = {'started_utc': now(), 'requested_model': payload['model']}
    dump(folder / 'metadata.json', meta)
    key = credential()
    try:
        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions', data=json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=420) as r:
            response = json.load(r)
        dump(folder / 'response.json', response)
        if 'error' in response:
            raise ValueError('API error: ' + str(response['error'])[:300])
        choice = response['choices'][0]
        if choice['finish_reason'] != 'stop':
            raise ValueError('Incomplete API response: ' + str(choice['finish_reason']))
        raw = choice['message']['content']
        (folder / 'raw.txt').write_text(raw)
        parsed = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip()), object_pairs_hook=unique_keys)
        if not isinstance(parsed, dict):
            raise ValueError('Expected a JSON object')
        dump(folder / 'parsed.json', parsed)
        meta.update(status='complete', returned_model=response.get('model'), provider=response.get('provider'),
                    response_id=response.get('id'), usage=response.get('usage'), completed_utc=now())
        dump(folder / 'metadata.json', meta)
        return parsed
    except Exception as e:
        meta.update(status='incomplete', error_type=type(e).__name__,
                    detail=str(e).replace(key, '[REDACTED]')[:300], completed_utc=now())
        dump(folder / 'metadata.json', meta)
        raise


def call(tag, model, system, user, max_tokens, respondent=False):
    """Call a model with up to three technical attempts, each cached under calls/<tag>/attempt_<n>."""
    messages = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': user}]
    last = None
    for attempt in range(3):
        payload = {'model': model, 'messages': messages,
                   'max_tokens': max_tokens if attempt == 0 else max(max_tokens, 6500),
                   'reasoning': {'effort': CONFIG['reasoning_effort']},
                   'response_format': {'type': 'json_object'},
                   'provider': {'allow_fallbacks': False, 'require_parameters': True}}
        if respondent:
            payload['provider']['only'] = [CONFIG['provider_pins'][model]]
            if CONFIG['temperature'].get(model) is not None:
                payload['temperature'] = CONFIG['temperature'][model]
        try:
            return _call_once(OUT / 'calls' / tag / f'attempt_{attempt}', payload)
        except Exception as e:
            if 'Budget cap' in str(e) or 'Cached request mismatch' in str(e):
                raise
            last = e
            time.sleep(1 + attempt)
    raise last


def wc(text):
    return len(text.split())


def facing(x, fmt):
    """Participant-facing fields only."""
    return {k: x[k] for k in (['title', 'opening', 'a', 'b'] if fmt == 'policy' else ['title', 'a', 'b'])}


def mechanical(x, fmt, case=None):
    """Code-based checks: required fields, word limits, A/B length ratio, researcher record."""
    errors = []
    for k in ['title', 'a', 'b'] + (['opening'] if fmt == 'policy' else []):
        if not isinstance(x.get(k), str) or not x[k].strip():
            errors.append('Missing string ' + k)
    if errors:
        return errors
    if not 3 <= wc(x['title']) <= 8:
        errors.append('Title must have 3-8 words')
    limits = {'opening': (80, 120), 'a': (20, 45), 'b': (20, 45)} if fmt == 'policy' else {'a': (80, 120), 'b': (80, 120)}
    for k, (lo, hi) in limits.items():
        if not lo <= wc(x[k]) <= hi:
            errors.append(f'{k} has {wc(x[k])} words; requires {lo}-{hi}')
    if max(wc(x['a']), wc(x['b'])) / min(wc(x['a']), wc(x['b'])) > 1.3:
        errors.append('A/B length ratio exceeds 1.30')
    if fmt == 'policy':
        r = x.get('researcher', {})
        for k in ['orientation_a', 'orientation_b', 'mechanism_a', 'mechanism_b', 'gain_a', 'gain_b',
                  'sacrifice_a', 'sacrifice_b', 'shared_goal', 'expected_success', 'horizon', 'costs',
                  'affected_groups', 'status_quo_a', 'status_quo_b']:
            if not isinstance(r.get(k), str) or not r[k].strip():
                errors.append('Missing researcher field ' + k)
        for side in ['a', 'b']:
            if r.get('orientation_' + side) != case['orientation_' + side]:
                errors.append('Intended mapping mismatch ' + side)
            if r.get('status_quo_' + side) not in ['NEW', 'INCREMENTAL', 'STATUS_QUO']:
                errors.append('Invalid status quo tag')
        if r.get('status_quo_a') != r.get('status_quo_b') and not r.get('status_quo_exception', '').strip():
            errors.append('Missing status quo exception')
        if not isinstance(r.get('limitations'), list):
            errors.append('Missing limitations list')
    elif not isinstance(x.get('adaptation_notes'), list):
        errors.append('Missing adaptation_notes list')
    return errors


def validate_checks(x, keys):
    if set(x.get('checks', {})) != set(keys):
        raise ValueError('Checker keys incomplete')
    for v in x['checks'].values():
        if v.get('result') not in ['PASS', 'FLAG'] or not v.get('evidence', '').strip():
            raise ValueError('Invalid check result')


def screen(fmt, x, tag):
    """Blind LLM screen: quality checks plus value classification, without the intended values."""
    def once(t):
        q = call(t, CONFIG['screening_model'], prompt(fmt + '_evaluation'),
                 json.dumps({'text': facing(x, fmt), 'question': QUESTION[fmt]}, ensure_ascii=False),
                 CONFIG['review_max_tokens'])
        validate_checks(q, CONFIG['quality_keys'])
        for side in ['a', 'b']:
            c = q['classification'][side]
            if (c.get('primary') not in VALUES + ['UNCLEAR'] or c.get('secondary') not in VALUES + ['NONE']
                    or c.get('ambiguity') not in ['CLEAR', 'BORDERLINE', 'UNCLEAR'] or not c.get('evidence')):
                raise ValueError('Invalid classification')
        return q
    try:
        return once(tag)
    except (ValueError, KeyError, TypeError):
        return once(tag + '_schema_retry')


def fidelity(policy, narrative, tag):
    """LLM check that the narrative pair preserves the policy case's material facts."""
    def once(t):
        q = call(t, CONFIG['screening_model'], prompt('cross_format_fidelity'),
                 json.dumps({'policy': facing(policy, 'policy'), 'narrative': facing(narrative, 'narrative')},
                            ensure_ascii=False), 3500)
        validate_checks(q, CONFIG['fidelity_keys'])
        return q
    try:
        return once(tag)
    except (ValueError, KeyError, TypeError):
        return once(tag + '_schema_retry')


def quality_flags(fmt, x, case, review):
    """All reasons a text fails: mechanical errors, flagged checks, and value classification mismatches."""
    flags = mechanical(x, fmt, case)
    flags += [k + ': ' + v['evidence'] for k, v in review['checks'].items() if v['result'] == 'FLAG']
    for side in ['a', 'b']:
        c = review['classification'][side]
        if c['primary'] != case['orientation_' + side] or c['ambiguity'] != 'CLEAR':
            flags.append(f"Value {side}: {c['primary']} / {c['ambiguity']}; intended {case['orientation_' + side]}")
    return flags


def fidelity_flags(f):
    return [k + ': ' + v['evidence'] for k, v in f['checks'].items() if v['result'] == 'FLAG']
