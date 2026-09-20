#!/usr/bin/env python3
"""Local orchestration experiment controller. Python standard library only."""
import argparse
import copy
import csv
import fcntl
import functools
import datetime as dt
import hashlib
import http.server
import json
import math
import os
from pathlib import Path
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
EXCLUDED = {'.git', 'node_modules', 'data', '.bench', '.DS_Store', '__pycache__'}
DIMENSIONS = ['correctness', 'completeness', 'maintainability', 'ux', 'evidence_quality']
PHASES = ['first', 'repaired']
EXPECTED = {'S1': {'R1','R2','R3'} | {f'F{i}' for i in range(1,12)}, 'S2': {'R1','R2','R3'} | {f'I{i}' for i in range(1,12)}, 'S3': {'R1','R2','R3'} | {f'U{i}' for i in range(1,9)}}


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def read(path): return json.loads(Path(path).read_text())
def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n'); temp.replace(path)
def require(condition, message):
    if not condition: raise ValueError(message)
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def inventory(folder):
    return {str(p.relative_to(folder)): digest(p) for p in sorted(Path(folder).rglob('*')) if p.is_file() and not any(x in EXCLUDED for x in p.relative_to(folder).parts)}
def copy_source(source, destination, extra=()):
    source = Path(source)
    for p in source.rglob('*'):
        if any(x in EXCLUDED or x in extra for x in p.relative_to(source).parts): continue
        require(not p.is_symlink(), f'Source symlink cannot be captured reproducibly: {p}')
    shutil.copytree(source, destination, ignore=lambda folder,names: [n for n in names if n in EXCLUDED or n in extra])
def command(argv, cwd, timeout=30):
    try:
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout)
        return {'exitCode': result.returncode, 'stdout': result.stdout[-20000:], 'stderr': result.stderr[-10000:]}
    except (subprocess.TimeoutExpired, OSError) as error:
        return {'exitCode': None, 'stdout':'', 'stderr':str(error), 'error':True}
def policy():
    files = [ROOT/'bench.py', ROOT/'bench/dashboard.html']
    for folder in ['seed','scenarios','evaluator','docs','methods']:
        files += [p for p in (ROOT/folder).rglob('*') if p.is_file() and not any(x in EXCLUDED for x in p.relative_to(ROOT).parts)]
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(files)}
def log(exp,event,**fields):
    with (exp/'events.jsonl').open('a') as f: f.write(json.dumps({'time':now(),'event':event,**fields})+'\n')
def load(exp): return read(exp/'experiment.json')
def save(exp,data): write(exp/'experiment.json',data)
def run_by_id(data,rid):
    for run in data['runs']:
        if run['id']==rid: return run
    raise ValueError('Unknown run ID')
def ensure_policy(data): require(data['policyHashes']==policy(), 'Bench files changed since preparation. Keep this experiment version fixed or prepare a new experiment; do not silently compare different tests.')
def folder_for(exp,run): return exp/'workspaces'/run['id']
def method_for(data,run): return run.get('methodFrozen') or next(m for m in data['methods'] if m['id']==run['method'])
def blank_review(scenario):
    return {'reviewer':'', 'scores':{key:{'value':None,'evidence':''} for key in DIMENSIONS}, 'manual':[dict(item,status='not_run',evidence='') for item in read(ROOT/'evaluator/manual.json')[scenario]], 'defects':[], 'notes':''}
def validate_review(value,scenario):
    require(isinstance(value,dict),'Review must be an object')
    require(isinstance(value.get('reviewer'),str) and value['reviewer'].strip(),'Reviewer name or anonymous reviewer ID is required')
    require(isinstance(value.get('scores'),dict) and set(value['scores'])==set(DIMENSIONS),'Include all five rubric dimensions')
    for score in value['scores'].values():
        require(isinstance(score,dict),'Score must contain value and evidence')
        n=score.get('value'); require(n is None or (type(n) is int and 0<=n<=3),'Scores must be integers 0–3 or null')
        require(isinstance(score.get('evidence'),str),'Score evidence must be text')
        if n is not None: require(score['evidence'].strip(),'Scored dimensions need evidence')
    manual=value.get('manual'); require(isinstance(manual,list),'Manual checks must be a list')
    expected={i['id'] for i in read(ROOT/'evaluator/manual.json')[scenario]}
    require(len(manual)==len(expected) and {i.get('id') for i in manual}==expected,'Manual check IDs must exactly match this scenario')
    for item in manual:
        require(item.get('status') in ['pass','fail','not_run'],'Invalid manual status')
        require(isinstance(item.get('evidence'),str),'Manual evidence must be text')
        if item['status']!='not_run': require(item['evidence'].strip(),'Executed manual checks need evidence')
    require(isinstance(value.get('defects'),list),'Defects must be a list')
    for defect in value['defects']:
        require(defect.get('severity') in ['critical','major','minor'],'Defect severity must be critical/major/minor')
        require(isinstance(defect.get('evidence'),str) and defect['evidence'].strip(),'Each defect needs reproduction/evidence')
    return value

def gate(evaluation, review):
    if not evaluation: return 'Not evaluated'
    if evaluation.get('status')=='error': return 'Evaluation error'
    if not evaluation.get('allPassed'): return 'Automated checks failed'
    if not review: return 'Manual review pending'
    if any(d['severity'] in ['critical','major'] for d in review['defects']): return 'Serious defect remains'
    if any(i['status']=='fail' for i in review['manual']): return 'Manual checks failed'
    if any(i['status']=='not_run' for i in review['manual']): return 'Manual review pending'
    if any(s['value'] is None for s in review['scores'].values()): return 'Rubric incomplete'
    if any(s['value'] < 2 for s in review['scores'].values()): return 'Quality bar not met'
    return 'Meets acceptance'

def prepare(exp,repeats):
    require(not exp.exists(),f'Experiment already exists: {exp}')
    require(repeats>=1 and repeats<=20,'Repeats must be 1–20')
    for binary in ['node','git']:
        require(shutil.which(binary),f'{binary} is required')
    major=int(subprocess.check_output(['node','--version'],text=True).strip().lstrip('v').split('.')[0]);require(major>=22,'Node 22+ is required')
    exp.mkdir(parents=True)
    scenarios=read(ROOT/'scenarios/catalog.json');methods=read(ROOT/'methods/defaults.json')
    data={'version':1,'createdAt':now(),'policyHashes':policy(),'seedHashes':inventory(ROOT/'seed'),'scenarios':scenarios,'methods':methods,'runs':[],'pairs':[]}
    for repeat in range(1,repeats+1):
        for si,scenario in enumerate(scenarios):
            # Latin-square ordering; rotates again on repeat.
            order=methods[(si+repeat-1)%3:]+methods[:(si+repeat-1)%3]
            for method in order:
                rid='run-'+secrets.token_hex(3)
                run={'id':rid,'scenario':scenario['id'],'method':method['id'],'repeat':repeat,'order':len(data['runs'])+1,'status':'prepared','phases':{},'metrics':{}}
                workspace=folder_for(exp,run);copy_source(ROOT/'seed',workspace)
                shutil.copyfile(ROOT/scenario['brief_file'],workspace/'TASK.md')
                (workspace/'AGENTS.md').write_text('# Benchmark participant rules\n\nRead TASK.md and LAUNCH.md. Work only in this assigned repository; do not inspect evaluator internals or sibling runs. Follow the run method recorded by the operator. Stop after reporting completion so the operator can capture the first submission. Do not deploy, publish, or use real user data.\n')
                git=command(['git','init','-q'],workspace);require(git['exitCode']==0,git['stderr'])
                command(['git','add','.'],workspace)
                result=command(['git','-c','user.name=Benchmark Fixture','-c','user.email=fixture@localhost','commit','-qm','Frozen Fieldnotes starting fixture'],workspace)
                require(result['exitCode']==0,result['stderr'])
                run['baselineCommit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=workspace,text=True).strip()
                run['initialHashes']=inventory(workspace)
                data['runs'].append(run)
    save(exp,data)
    for run in data['runs']: write_launch(exp,data,run)
    log(exp,'prepared',runs=len(data['runs']),repeats=repeats)
    print(f'Prepared {len(data["runs"])} isolated repositories at {exp}\nNo agent runs have started.\nOpen the bench: python3 bench.py --experiment "{exp}" serve')


def write_launch(exp,data,run):
    (folder_for(exp,run)/'LAUNCH.md').write_text(launch_text(exp,data,run))

def launch_text(exp,data,run):
    method=method_for(data,run);scenario=next(s for s in data['scenarios'] if s['id']==run['scenario'])
    prompts={
    'solo':'Complete TASK.md as a single agent. Use the recorded model and reasoning setting. Do not delegate. You may plan, self-review, run tests, and correct your work within the allowance.',
    'written-handoff':'PLANNER SESSION: Read TASK.md and inspect the baseline. Produce HANDOFF.md with a self-contained implementation plan, ownership, dependencies, validation, and integration acceptance. Do not implement. Stop after the handoff.\n\nEXECUTOR SESSION (fresh, configured recipient): Read TASK.md and HANDOFF.md. Implement and verify under the recorded delegation policy. The planner does not actively steer this session. Planning and execution count toward the same allowance.',
    'active-orchestration':'ORCHESTRATOR SESSION: Read TASK.md. Actively direct the configured implementers, coordinate ownership and integration, review progress, and ensure final acceptance. Follow the exact model roles and delegation limits below. All participants and integration count toward the allowance. Do not replace models. The final integrated source belongs in this assigned repository.'}
    return f'''# Run {run['id']} · {run['scenario']} · repeat {run['repeat']}

Working directory: `{folder_for(exp,run)}`

{prompts[method['mode']]}

## Frozen setup at start

```json
{json.dumps(method,indent=2)}
```

Read TASK.md for the complete request and acceptance contract. Use a fresh session with only this repository. Keep independent attempts isolated. Do not read the benchmark controller, evaluator, or other runs.

First-attempt allowance: {scenario['minutes']} minutes, including preparation. Repair allowance (only after the operator freezes and reviews the first result): {scenario['repair']} minutes. The bench records but does not automatically terminate agent sessions.

Before coding, save APPROACH.md. When done, save SUBMISSION.md with actual verification evidence and remaining gaps, then stop. Do not see external evaluator results until first capture. A blocked or unfinished task is a valid experimental result; report it honestly.

This file describes a method, not a mechanism to select models or dispatch agents. The operator must launch the named models/settings in their tools. If the setup is unconfigured, configure it before starting.
'''

def configure(exp,mid,value):
    data=load(exp);ensure_policy(data)
    require(not any(r['method']==mid and r.get('startedAt') for r in data['runs']),'This method already has started runs. Prepare a new experiment to change its definition.')
    old=next((m for m in data['methods'] if m['id']==mid),None);require(old,'Unknown method')
    require(isinstance(value,dict) and value.get('id')==mid and value.get('mode')==old['mode'],'Keep method ID and mode unchanged')
    require(isinstance(value.get('configured'),bool),'configured must be true or false')
    require(isinstance(value.get('label'),str) and value['label'].strip(),'Method label required')
    require(isinstance(value.get('roles'),list) and value['roles'],'At least one model role required')
    for role in value['roles']:
        require(isinstance(role,dict) and all(isinstance(role.get(k),str) and role[k].strip() for k in ['role','model','reasoning']),'Every role needs role/model/reasoning text; use n/a when appropriate')
    require(isinstance(value.get('transport'),str) and value['transport'].strip(),'Transport/runtime description required')
    if value['configured']: require('RECORD ' not in json.dumps(value),'Replace all RECORD placeholders before marking configured')
    data['methods'][data['methods'].index(old)]=value;save(exp,data)
    for run in data['runs']:
        if run['method']==mid: write_launch(exp,data,run)
    log(exp,'method_configured',method=mid,definition=value)

def start(exp,rid):
    data=load(exp);ensure_policy(data);run=run_by_id(data,rid);require(not run.get('startedAt'),'Run already started')
    method=method_for(data,run);require(method.get('configured'),'Configure exact roles/settings/transport for this method first')
    actual=inventory(folder_for(exp,run));actual.pop('LAUNCH.md',None)
    require(actual==run['initialHashes'],'Workspace differs from its starting fixture. Prepare a fresh experiment instead of starting after edits.')
    run['methodFrozen']=copy.deepcopy(method);run['startedAt']=now();run['status']='running';write_launch(exp,data,run);save(exp,data);log(exp,'started',run=rid,method=method)
    print(f'Started {rid}. Paste {folder_for(exp,run)/"LAUNCH.md"} into the configured fresh session.')

def repair(exp,rid):
    data=load(exp);ensure_policy(data);run=run_by_id(data,rid)
    require('first' in run['phases'],'Capture first submission before repair');require('evaluation' in run['phases']['first'],'Evaluate first submission before repair')
    require(not run.get('repairStartedAt'),'Repair already started');run['repairStartedAt']=now();run['status']='repairing';save(exp,data);log(exp,'repair_started',run=rid)
    print(f'Repair clock started for {rid}. First submission remains preserved.')

def capture(exp,rid,phase):
    data=load(exp);ensure_policy(data);run=run_by_id(data,rid)
    start_time=run.get('startedAt' if phase=='first' else 'repairStartedAt');require(start_time,f'Start the {phase} phase before capture')
    require(phase not in run['phases'],'This phase is already captured and cannot be overwritten')
    workspace=folder_for(exp,run);destination=exp/'snapshots'/rid/phase
    require(not destination.exists(),'Snapshot directory already exists; inspect state before retrying')
    # Check task integrity but preserve the capture for honest scoring if participant changed it.
    end=now();pre=inventory(workspace)
    destination.parent.mkdir(parents=True,exist_ok=True);copy_source(workspace,destination)
    hashes=inventory(destination)
    require(pre==inventory(workspace)==hashes,'Workspace changed during capture. Stop all agent writes; inspect this incomplete capture before retrying.')
    elapsed=(dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(start_time)).total_seconds()/60
    scenario=next(s for s in data['scenarios'] if s['id']==run['scenario']);limit=scenario['minutes' if phase=='first' else 'repair']
    receipt={'capturedAt':end,'elapsedMinutes':round(elapsed,3),'allowanceMinutes':limit,'overBudget':elapsed>limit,'hashes':hashes,'taskIntact':digest(workspace/'TASK.md')==data['policyHashes'][f'scenarios/{run["scenario"]}.md'] if (workspace/'TASK.md').exists() else False,'gitHead':command(['git','rev-parse','HEAD'],workspace),'gitStatus':command(['git','status','--short'],workspace),'gitDiff':command(['git','diff','HEAD','--'],workspace)}
    write(exp/'receipts'/rid/f'{phase}.json',receipt)
    run['phases'][phase]={'capturedAt':end,'elapsedMinutes':receipt['elapsedMinutes'],'allowanceMinutes':limit,'overBudget':elapsed>limit,'taskIntact':receipt['taskIntact']}
    run['status']='captured';save(exp,data);log(exp,'captured',run=rid,phase=phase,elapsedMinutes=receipt['elapsedMinutes'],overBudget=elapsed>limit)
    print(f'Captured {rid}/{phase}: {len(hashes)} files; {elapsed:.1f}/{limit} minutes. Next: evaluate {rid} --phase {phase}')

def evaluate(exp,rid,phase):
    data=load(exp);ensure_policy(data);run=run_by_id(data,rid);require(phase in run['phases'],'Capture before evaluating')
    require('evaluation' not in run['phases'][phase],'Evaluation already exists. Preserve this result; use a new phase/run for changes.')
    snapshot=exp/'snapshots'/rid/phase;receipt=read(exp/'receipts'/rid/f'{phase}.json')
    require(inventory(snapshot)==receipt['hashes'],'Snapshot integrity check failed; evaluation refused')
    outputdir=exp/'results'/rid/phase;outputdir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='orchestration-eval-') as temp:
        candidate=Path(temp)/'submission';copy_source(snapshot,candidate)
        (candidate/'tests').mkdir(exist_ok=True)
        shutil.copyfile(ROOT/'seed/tests/smoke.test.mjs',candidate/'tests/bench-original.test.mjs')
        smoke=command(['node','--test','tests/bench-original.test.mjs'],candidate,30)
        raw=Path(temp)/'checks.json'
        checks_run=command(['node',str(ROOT/'evaluator/checks.mjs'),run['scenario'],str(candidate),str(raw)],ROOT,180)
        report=read(raw) if raw.exists() else {'checks':[],'passed':0,'total':0,'allPassed':False}
        valid=(len(report.get('checks',[]))==len(EXPECTED[run['scenario']]) and {c['id'] for c in report.get('checks',[])}==EXPECTED[run['scenario']] and checks_run['exitCode'] in [0,1] and smoke['exitCode'] is not None)
        report.update(status='complete' if valid else 'error',smoke=smoke,runner=checks_run,evaluatedAt=now(),snapshotVerified=True)
        report['allPassed']=valid and report['allPassed'] and smoke['exitCode']==0 and receipt['taskIntact']
        if not receipt['taskIntact']:report['integrityNote']='Participant changed or removed TASK.md'
        write(outputdir/'evaluation.json',report)
    run['phases'][phase]['evaluation']=report;save(exp,data);log(exp,'evaluated',run=rid,phase=phase,status=report['status'],passed=report['passed'],total=report['total'])
    print(f'{rid}/{phase}: {report["passed"]}/{report["total"]} checks; baseline smoke exit {smoke["exitCode"]}; {gate(report,None)}')

def save_review(exp,rid,phase,value):
    data=load(exp);run=run_by_id(data,rid);require(phase in run['phases'],'Capture before reviewing');validate_review(value,run['scenario'])
    dest=exp/'results'/rid/phase/'review.json'
    if dest.exists():
        history=dest.parent/'review-history';history.mkdir(exist_ok=True);shutil.copyfile(dest,history/f'{time.time_ns()}.json')
    write(dest,value);run['phases'][phase]['review']=value;save(exp,data);log(exp,'review_saved',run=rid,phase=phase)

def metrics(exp,rid,phase,value):
    data=load(exp);run=run_by_id(data,rid)
    require(isinstance(value,dict),'Metrics must be an object')
    allowed={'costUSD','inputTokens','outputTokens','humanMinutes','interventions','notes','source'};require(set(value)<=allowed,'Unknown metric field')
    for key in allowed-{'notes','source'}:
        n=value.get(key)
        require(n is None or (type(n) in [int,float] and math.isfinite(n) and n>=0),f'{key} must be nonnegative or null')
        if key in ['inputTokens','outputTokens','interventions'] and n is not None: require(type(n) is int,f'{key} must be an integer')
    for key in ['notes','source']:require(isinstance(value.get(key,''),str),f'{key} must be text')
    if any(value.get(k) is not None for k in allowed-{'notes','source'}): require(value.get('source','').strip(),'Record measurement source (provider usage/export, stopwatch, etc.)')
    run['metrics'][phase]=value;save(exp,data);log(exp,'metrics_saved',run=rid,phase=phase,metrics=value)

def blind(exp,phase):
    data=load(exp);ensure_policy(data);selected=[r for r in data['runs'] if 'evaluation' in r['phases'].get(phase,{})]
    require(selected,'Evaluate captured submissions before exporting blind packages')
    random.SystemRandom().shuffle(selected)
    for run in selected:
        details=run['phases'][phase]
        label=details.setdefault('blindLabel','B-'+secrets.token_hex(3).upper())
        dest=exp/'blind'/phase/label
        if dest.exists(): continue
        source=exp/'snapshots'/run['id']/phase
        require(inventory(source)==read(exp/'receipts'/run['id']/f'{phase}.json')['hashes'],'Snapshot integrity check failed')
        dest.mkdir(parents=True);copy_source(source,dest/'submission',extra=('LAUNCH.md','APPROACH.md','SUBMISSION.md','HANDOFF.md','AGENTS.md'))
        write(dest/'review.json',blank_review(run['scenario']))
        (dest/'REVIEW.md').write_text(f'# {label} · {run["scenario"]} · repeat {run["repeat"]} · {phase}\n\nRun the app in submission/. Use a fresh DATA_FILE and unique PORT. Complete review.json; never edit submitted code.\n\n'+(ROOT/'docs/REVIEWER_PROMPT.md').read_text()+'\n'+(ROOT/'docs/RUBRIC.md').read_text())
        if 'evaluation' in details: write(dest/'evaluation.json',details['evaluation'])
    save(exp,data);log(exp,'blind_export',phase=phase,count=len(selected));print(f'Blind reviewer packages: {exp/"blind"/phase}')

def pair(exp,a,b,phase,preference,evidence,reviewer):
    data=load(exp);ra=run_by_id(data,a);rb=run_by_id(data,b)
    require(a!=b and ra['scenario']==rb['scenario'] and ra['repeat']==rb['repeat'],'Compare different runs of the same scenario and repeat')
    require(all(phase in r['phases'] and r['phases'][phase].get('review') for r in [ra,rb]),'Save both individual reviews first')
    require(preference in ['a','b','tie','incomparable'],'Invalid preference')
    require(isinstance(evidence,str) and evidence.strip() and isinstance(reviewer,str) and reviewer.strip(),'Pairwise judgment needs evidence and reviewer')
    data['pairs'].append({'a':a,'b':b,'phase':phase,'preference':preference,'evidence':evidence,'reviewer':reviewer,'at':now()});save(exp,data);log(exp,'pair_reviewed',a=a,b=b,phase=phase)

def view(exp):
    data=load(exp);result=copy.deepcopy(data);result.pop('policyHashes',None);result.pop('seedHashes',None)
    for run in result['runs']:
        run.pop('initialHashes',None);run['workspace']=str(folder_for(exp,run));run['launch']=launch_text(exp,data,run);run['methodLabel']=method_for(data,run)['label']
        run['reviewTemplate']=blank_review(run['scenario'])
        for phase,details in run['phases'].items(): details['gate']=gate(details.get('evaluation'),details.get('review'))
    result['experimentPath']=str(exp);result['controllerPath']=str(ROOT/'bench.py');result['integrityOK']=data['policyHashes']==policy()
    return result

def export(exp):
    data=view(exp);out=exp/'exports';out.mkdir(exist_ok=True);write(out/'results.json',data)
    fields=['run','scenario','repeat','method','phase','gate','passed','total','elapsedMinutes','overBudget','critical','major','minor']+DIMENSIONS+['costUSD','humanMinutes','interventions','inputTokens','outputTokens']
    with (out/'results.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for run in data['runs']:
            for phase in PHASES:
                details=run['phases'].get(phase,{});ev=details.get('evaluation',{});review=details.get('review');m=run['metrics'].get(phase,{})
                row={'run':run['id'],'scenario':run['scenario'],'repeat':run['repeat'],'method':run['methodLabel'],'phase':phase,'gate':details.get('gate','Not captured'),'passed':ev.get('passed'),'total':ev.get('total'),'elapsedMinutes':details.get('elapsedMinutes'),'overBudget':details.get('overBudget')}
                for severity in ['critical','major','minor']: row[severity]=sum(d['severity']==severity for d in review['defects']) if review else None
                for dimension in DIMENSIONS:row[dimension]=review['scores'][dimension]['value'] if review else None
                for key in ['costUSD','humanMinutes','interventions','inputTokens','outputTokens']:row[key]=m.get(key)
                writer.writerow(row)
    print(f'Exported {out/"results.csv"} and results.json. Missing values remain blank; no automatic winner.')

def serve(exp,port,open_browser):
    token=secrets.token_urlsafe(24)
    class Handler(http.server.BaseHTTPRequestHandler):
        def send(self,status,value,ctype='application/json'):
            body=(json.dumps(value) if ctype=='application/json' else value).encode();self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def valid_host(self): return self.headers.get('Host','') in [f'127.0.0.1:{port}',f'localhost:{port}']
        def do_GET(self):
            if not self.valid_host():return self.send(403,{'error':'Local host required'})
            try:
                with LOCK:
                    if self.path=='/':return self.send(200,(ROOT/'bench/dashboard.html').read_text().replace('__BENCH_TOKEN__',token),'text/html; charset=utf-8')
                    if self.path=='/api/data':return self.send(200,view(exp))
                self.send(404,{'error':'Not found'})
            except Exception as e:self.send(400,{'error':str(e)})
        def do_POST(self):
            if not self.valid_host() or self.headers.get('X-Bench-Token')!=token:return self.send(403,{'error':'Use this local bench page'})
            try:
                length=int(self.headers.get('Content-Length','0'));require(0<length<=500000,'Invalid body length');body=json.loads(self.rfile.read(length))
                with LOCK:
                    if self.path=='/api/review':
                        require(body['phase'] in PHASES,'Invalid phase');save_review(exp,body['run'],body['phase'],body['review'])
                    elif self.path=='/api/metrics':
                        require(body['phase'] in PHASES,'Invalid phase');metrics(exp,body['run'],body['phase'],body['metrics'])
                    elif self.path=='/api/configure': configure(exp,body['method'],body['definition'])
                    elif self.path=='/api/pair':
                        require(body['phase'] in PHASES,'Invalid phase');pair(exp,body['a'],body['b'],body['phase'],body['preference'],body['evidence'],body['reviewer'])
                    else:return self.send(404,{'error':'Not found'})
                self.send(200,{'ok':True})
            except Exception as e:self.send(400,{'error':str(e)})
        def log_message(self,*args): pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler)
    url=f'http://127.0.0.1:{port}';print(f'Bench available at {url}\nExperiment: {exp}\nCtrl-C stops the bench; saved reviews remain.',flush=True)
    if open_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


# Serialize mutations across Terminal commands and the dashboard server.
def locked(function):
    @functools.wraps(function)
    def call(exp, *args, **kwargs):
        with LOCK, (exp / '.controller.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try: return function(exp, *args, **kwargs)
            finally: fcntl.flock(lock, fcntl.LOCK_UN)
    return call

for _name in ['configure', 'start', 'repair', 'capture', 'evaluate', 'save_review', 'metrics', 'blind', 'pair', 'export']:
    globals()[_name] = locked(globals()[_name])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--experiment',type=Path,default=ROOT/'experiments/pilot')
    sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('prepare');p.add_argument('--repeats',type=int,default=1)
    sub.add_parser('status')
    p=sub.add_parser('configure');p.add_argument('method');p.add_argument('--file',type=Path,required=True)
    for name in ['start','repair']:
        p=sub.add_parser(name);p.add_argument('run')
    for name in ['capture','evaluate','metrics']:
        p=sub.add_parser(name);p.add_argument('run');p.add_argument('--phase',choices=PHASES,default='first')
        if name=='metrics':p.add_argument('--file',type=Path,required=True)
    p=sub.add_parser('review');g=p.add_mutually_exclusive_group(required=True);g.add_argument('--run');g.add_argument('--blind');p.add_argument('--phase',choices=PHASES,default='first');p.add_argument('--file',type=Path,required=True)
    p=sub.add_parser('blind');p.add_argument('--phase',choices=PHASES,default='first')
    sub.add_parser('export')
    p=sub.add_parser('serve');p.add_argument('--port',type=int,default=4387);p.add_argument('--open',action='store_true')
    args=parser.parse_args();exp=args.experiment.expanduser().resolve()
    try:
        if args.cmd=='prepare':return prepare(exp,args.repeats)
        require((exp/'experiment.json').exists(),'Experiment missing; run prepare first')
        if args.cmd=='status':
            data=view(exp)
            for r in data['runs']:print(f'{r["order"]:2} {r["id"]} {r["scenario"]} r{r["repeat"]} {r["methodLabel"]:38} {r["status"]}')
        elif args.cmd=='configure':configure(exp,args.method,read(args.file))
        elif args.cmd=='start':start(exp,args.run)
        elif args.cmd=='repair':repair(exp,args.run)
        elif args.cmd=='capture':capture(exp,args.run,args.phase)
        elif args.cmd=='evaluate':evaluate(exp,args.run,args.phase)
        elif args.cmd=='metrics':metrics(exp,args.run,args.phase,read(args.file))
        elif args.cmd=='review':
            rid=args.run
            if args.blind:
                matches=[r for r in load(exp)['runs'] if r['phases'].get(args.phase,{}).get('blindLabel')==args.blind];require(len(matches)==1,'Unknown blind label');rid=matches[0]['id']
            save_review(exp,rid,args.phase,read(args.file))
        elif args.cmd=='blind':blind(exp,args.phase)
        elif args.cmd=='export':export(exp)
        elif args.cmd=='serve':serve(exp,args.port,args.open)
    except (ValueError,KeyError,TypeError,json.JSONDecodeError,OSError) as error:
        print(f'Error: {error}',file=sys.stderr);return 2
    return 0

if __name__=='__main__':sys.exit(main())
