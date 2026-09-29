#!/usr/bin/env python3
"""Run inside Kubernetes: fresh connections to ClusterIP, bounded sustained load."""
import concurrent.futures as cf
import json,math,os,ssl,threading,time,urllib.request
from pathlib import Path
BASE='http://vllm.vllm-lab.svc.cluster.local:8000'
PROM='http://prometheus.vllm-lab.svc.cluster.local:9090'
DURATION=int(os.getenv('DURATION','300')); CONCURRENCY=int(os.getenv('CONCURRENCY','24'))
if DURATION <= 0 or not 1 <= CONCURRENCY <= 32:
 raise SystemExit('DURATION must be positive; CONCURRENCY must be 1..32')
OUT=Path(os.getenv('RESULTS_DIR','/results/run'));OUT.mkdir(parents=True,exist_ok=False)
lock=threading.Lock();stop=threading.Event();rows=[];samples=[];started=time.monotonic()
def fetch(url,body=None,timeout=15):
 req=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Connection':'close'})
 return urllib.request.urlopen(req,timeout=timeout)
def prom_raw():
 # Pod discovery is essential: snapshot each backend independently.
 with fetch(PROM+'/api/v1/targets') as r: targets=json.load(r)['data']['activeTargets']
 result={}
 for target in targets:
  if target['labels'].get('job')=='vllm':
   try:
    with fetch(target['scrapeUrl'],timeout=4) as r:result[target['labels']['pod']]=r.read().decode()
   except Exception as e: result[target['labels']['pod']]={'error':str(e)}
 return result
TOKEN=Path('/var/run/secrets/kubernetes.io/serviceaccount/token').read_text()
TLS=ssl.create_default_context(cafile='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt')
def kube(path):
 req=urllib.request.Request('https://kubernetes.default.svc'+path,headers={'Authorization':'Bearer '+TOKEN})
 with urllib.request.urlopen(req,context=TLS,timeout=10) as r:return json.load(r)
def monitor():
 while not stop.is_set():
  row={'elapsed_s':time.monotonic()-started}
  try:
   row['deployment']=kube('/apis/apps/v1/namespaces/vllm-lab/deployments/vllm')
   row['pod_metrics']=kube('/apis/metrics.k8s.io/v1beta1/namespaces/vllm-lab/pods')
   row['pods']=kube('/api/v1/namespaces/vllm-lab/pods?labelSelector=app%3Dvllm')
   row['inference_metrics']=prom_raw()
  except Exception as e:row['error']=str(e)
  samples.append(row)
  with (OUT/'samples.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
  print('SAMPLE',round(row['elapsed_s']), 'desired',row.get('deployment',{}).get('spec',{}).get('replicas'),'ready',row.get('deployment',{}).get('status',{}).get('readyReplicas',0),flush=True)
  stop.wait(5)
# Tokenize once through the Service. Each actual request changes early token IDs.
with fetch(BASE+'/tokenize',{'model':'lab-small','prompt':' '.join(['Inspect this request queue and latency event.']*200)}) as r:template=json.load(r)['tokens'][:700]
assert len(template)==700
(OUT/'before.json').write_text(json.dumps(prom_raw()))
t=threading.Thread(target=monitor);t.start();deadline=time.monotonic()+DURATION
counter=0
def worker(worker_id):
 global counter
 while time.monotonic()<deadline:
  with lock:seq=counter;counter+=1
  tokens=template.copy();tokens[:8]=[20+(seq//(10**i))%10 for i in range(8)]
  start=time.monotonic();first=None;done=False
  row={'id':seq,'worker':worker_id,'start_s':start-started}
  try:
   with fetch(BASE+'/v1/completions',{'model':'lab-small','prompt':tokens,'max_tokens':128,'ignore_eos':True,'temperature':0,'stream':True,'stream_options':{'include_usage':True}},timeout=240) as r:
    for line in r:
     if not line.startswith(b'data: '):continue
     value=line[6:].strip()
     if value==b'[DONE]':done=True;break
     data=json.loads(value)
     if data.get('error'):raise RuntimeError(data['error'])
     if data.get('usage'):row['usage']=data['usage']
     if first is None and any(c.get('text') for c in data.get('choices',[])):first=time.monotonic()
   assert done and first is not None
   assert row['usage']['prompt_tokens']==700 and row['usage']['completion_tokens']==128
   row.update(ok=True,ttft_s=first-start,e2e_s=time.monotonic()-start)
  except Exception as e:row.update(ok=False,error=str(e),e2e_s=time.monotonic()-start)
  with lock:
   rows.append(row)
   with (OUT/'requests.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
try:
 with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:list(pool.map(worker,range(CONCURRENCY)))
 time.sleep(10)
finally:stop.set();t.join()
(OUT/'after.json').write_text(json.dumps(prom_raw()))
summary={'duration_s':DURATION,'concurrency':CONCURRENCY,'elapsed_s':time.monotonic()-started,'requests':len(rows),'successes':sum(r['ok'] for r in rows),'service':BASE}
for metric in ['ttft_s','e2e_s']:
 values=sorted(r[metric] for r in rows if r['ok']);summary[metric]={'mean':sum(values)/len(values),'p95':values[math.ceil(.95*len(values))-1]} if values else None
(OUT/'summary.json').write_text(json.dumps(summary,indent=2));print('RESULT',json.dumps(summary),flush=True)
if any(not r['ok'] for r in rows):raise SystemExit(1)
