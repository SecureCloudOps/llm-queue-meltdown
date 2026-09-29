#!/usr/bin/env python3
import argparse,json,math,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();d=a.directory
samples=[json.loads(x) for x in (d/'samples.jsonl').read_text().splitlines()];requests=[json.loads(x) for x in (d/'requests.jsonl').read_text().splitlines()]
before=json.loads((d/'before.json').read_text());after=json.loads((d/'after.json').read_text())
def parse(raw):
 vals={}
 if not isinstance(raw,str):return vals
 for line in raw.splitlines():
  if line.startswith('#') or not line:continue
  key,val=line.rsplit(' ',1);vals[key]=float(val)
 return vals
def metric(vals,name):return sum(v for k,v in vals.items() if k.split('{')[0]==name)
last={k:parse(v) for k,v in before.items()};counts={};totals={};buckets={};wait=[];cpu=[];ram=[];ready=[];first_three=None
for sample in samples+[{'inference_metrics':after}]:
 waiting=0
 for pod,raw in sample.get('inference_metrics',{}).items():
  if not isinstance(raw,str):continue
  vals=parse(raw);waiting+=metric(vals,'vllm:num_requests_waiting')
  old=last.get(pod,{})
  for name in ['vllm:request_queue_time_seconds_count','vllm:request_queue_time_seconds_sum','vllm:e2e_request_latency_seconds_count']:
   delta=metric(vals,name)-metric(old,name)
   # Counter reset: retain observations before reset and start new segment.
   if delta<0:delta=metric(vals,name)
   totals[name]=totals.get(name,0)+delta
   if name.endswith('e2e_request_latency_seconds_count'):counts[pod]=counts.get(pod,0)+delta
  for key,val in vals.items():
   if key.startswith('vllm:request_queue_time_seconds_bucket{'):
    bound=float(re.search('le="([^"]+)"',key).group(1));delta=val-old.get(key,0)
    buckets[bound]=buckets.get(bound,0)+(val if delta<0 else delta)
  last[pod]=vals
 if 'elapsed_s' not in sample:continue
 wait.append(waiting)
 status=sample.get('deployment',{}).get('status',{});r=status.get('readyReplicas',0);ready.append(r)
 if r==3 and first_three is None:first_three=sample['elapsed_s']
 cores=0
 for pod in sample.get('pod_metrics',{}).get('items',[]):
  if not pod['metadata']['name'].startswith('vllm-'):continue
  for c in pod['containers']:
   value=c['usage']['cpu'];cores+=float(value[:-1])/({'n':1e9,'u':1e6,'m':1e3}[value[-1]]) if value[-1] in 'num' else float(value)
   mem=c['usage']['memory'];ram.append(float(mem[:-2])/1024 if mem.endswith('Ki') else float(mem[:-2]) if mem.endswith('Mi') else float(mem)/1048576)
 cpu.append(cores)
def percentile(key,rows):
 nums=sorted(r[key] for r in rows if r.get('ok'));return nums[math.ceil(len(nums)*.95)-1] if nums else None
n=buckets.get(float('inf'),0);low=prev=0;qp=None
for high,count in sorted(buckets.items()):
 if count>=.95*n and count>prev:
  qp={'estimate_s':low+(high-low)*(.95*n-prev)/(count-prev),'bucket_low_s':low,'bucket_high_s':high};break
 low,prev=high,count
result={'requests':len(requests),'successes':sum(r.get('ok',False) for r in requests),'p95_ttft_s':percentile('ttft_s',requests),'p95_e2e_s':percentile('e2e_s',requests),'p95_queue_histogram':qp,'mean_queue_s':totals['vllm:request_queue_time_seconds_sum']/totals['vllm:request_queue_time_seconds_count'],'max_waiting':max(wait),'max_ready':max(ready),'first_three_ready_s':first_three,'max_desired':max(s.get('deployment',{}).get('spec',{}).get('replicas',0) for s in samples),'cpu_total_mean_cores':sum(cpu)/len(cpu),'cpu_total_max_cores':max(cpu),'max_pod_working_set_mib':max(ram),'completions_by_pod':counts,'telemetry_errors':[s['error'] for s in samples if 'error'in s]}
if first_three is not None:
 steady=[r for r in requests if r['start_s']>=first_three];result['after_three_ready']={'requests':len(steady),'p95_ttft_s':percentile('ttft_s',steady),'p95_e2e_s':percentile('e2e_s',steady)}
(d/'analysis.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
