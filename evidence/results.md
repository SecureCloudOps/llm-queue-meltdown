# Experiment results — September 28–29, 2026

Both runs used SmolLM2-135M-Instruct, BF16, the same serving limits, 24 concurrent clients, and a five-minute dispatch window. Every request contained 700 input tokens and generated 128 output tokens. Outstanding requests were allowed to finish. Requests went to the ClusterIP DNS name inside Kubernetes using fresh connections; no port-forward was used.

| Metric | One fixed replica | KEDA enabled |
|---|---:|---:|
| Ready replicas | 1 | 1 → 3 |
| Successful requests | 65/65 | 105/105 |
| Mean TTFT | 90.96 s | 37.57 s |
| P95 TTFT | 118.78 s | 116.15 s |
| Mean queue time | 84.70 s | 31.56 s |
| P95 queue time (histogram estimate) | 118.53 s | 113.86 s |
| Mean E2E latency | 133.69 s | 72.96 s |
| P95 E2E latency | 164.26 s | 160.74 s |
| Peak sampled waiting requests | 22 | 23 |
| Mean aggregate vLLM CPU | 0.97 cores | 2.47 cores |
| Peak aggregate vLLM CPU | 1.00 cores | 3.00 cores |
| Peak sampled per-pod RAM | 2899 MiB | 2885 MiB |

## Usable-capacity proof

KEDA scaled 1 → 3 Ready replicas in **76 seconds** (first sampled at 76.18 s). Pod memory was approximately **2.7–2.9 GiB**: one snapshot recorded 2737, 2759, and 2884 MiB. Per-pod completion-counter increases during the autoscaled run:

- `vllm-dc6c588d8-zlbbv`: 53 completed requests.
- `vllm-dc6c588d8-vfzcn`: 25 completed requests.
- `vllm-dc6c588d8-64k6q`: 27 completed requests.

All three remained Ready with zero model-container restarts during the test. KEDA was resumed from the one-replica baseline; these replicas were added by the waiting-request trigger, not by manual scaling. The memory fit required a smaller model and a 12 GiB VM; three Qwen replicas did not pass.

Request failures: **zero** (65/65 baseline; 105/105 autoscaled). Model-container restarts: **zero** in both runs, verified from sampled container statuses. No telemetry errors were recorded.

## Interpretation

The scaler now adds usable serving capacity, and the Kubernetes Service distributes new requests to it. Average queue time and latency improved, and more requests completed under the same concurrency and dispatch duration. Overall p95 and maximum waiting depth did not improve dramatically: the run includes cold-start backlog, and existing queued requests stay on the original pod.

For the 75 requests started after all three replicas became Ready, p95 TTFT was 79.28 s and p95 E2E was 124.66 s. This subset is supplementary; it is not a replacement for the full-run comparison.

CPU was saturated per active pod, not low. Aggregate CPU rises as replicas add compute. This does not demonstrate that a properly normalized CPU dashboard would miss the overload, nor that a latency SLO has been met.

## Measurement limits

Queue p95 estimates interpolate within the same broad 60–120 s bucket in both runs; the apparent small difference is not precise. Client TTFT/E2E percentiles use individual streaming request timings. Mean queue time uses server histogram counter deltas. Metrics and CPU were sampled approximately every five seconds and can miss short peaks.

This is a fixed-concurrency closed-loop workload, not a fixed arrival rate: faster responses allow more requests. Baseline elapsed time including drain was 420.49 s; autoscaled elapsed time was 349.58 s. Each scenario ran once, on separate days, so these are descriptive lab results, not statistically controlled performance guarantees.

## Investigation history (separate configurations)

These earlier Qwen2.5-0.5B results explain the remediation; they are not the
baseline for the SmolLM2 comparison above.

- Initial FP32 startup exceeded a 6 GiB limit. A 7 GiB limit passed smoke
  checks; idle memory was 6134 MiB with four sequences and a 1 GiB KV cache.
  Eight sequences gave 6821 MiB after a smoke test. Reducing KV cache to
  256 MiB gave 6627 MiB initially and 6098 MiB after settling: still above 4 GiB.
- A single 700-input/128-output-token request had 0.0002 s mean queue time,
  2.76 s client TTFT and 12.77 s client E2E. A 24-request burst increased
  mean queue time to 45.95 s, mean TTFT to 53.26 s and mean E2E to 85.43 s;
  p95 TTFT/E2E were 102.17/119.45 s. All requests succeeded, health stayed
  HTTP 200, waiting peaked at 21 and CPU reached the two-core pod limit.
- The instrumentation repeat recorded 46.11 s mean queue time, 54.57 s
  server TTFT and 86.77 s server E2E; client p95 TTFT/E2E were
  102.83/120.89 s. KV occupancy peaked at 66.7%, with no demonstrated
  cache exhaustion. Peak cgroup memory was 6204 MiB; cgroup total and
  metrics-server working-set memory are different measurements.
- The first KEDA burst completed 24/24 requests, with client p95 TTFT
  105.19 s and E2E 122.79 s. Desired replicas reached three, but only one
  became Ready: the others were Pending for insufficient CPU and memory.
  A repeat completed 24/24 with mean queue 44.85 s and client p95 TTFT
  101.59 s. Neither run demonstrated a latency fix or usable scale-out.
  Port-forward traffic also selected one pod rather than balancing requests.
- BF16, smaller batches and cache brought Qwen memory to about 3.7–4 GiB,
  but three startups exhausted even the expanded 12 GiB VM: a model
  restarted and the load generator was OOM-killed. Switching to SmolLM2
  and retaining adequate VM headroom enabled the final comparison.

## Provenance

During repository cleanup, both final analyses were recomputed from the
original per-pod before/after metrics, sampled metrics and request records;
rounded values matched this report. Sampled model restart counts were zero.
Original run labels were `sustained-before` and `sustained-after`. Redundant
reports, raw captures, cluster dumps and intermediate manifests were removed
from the public tree after review. This document retains the validated
measurements and relevant historical findings; the original raw runs are
not included, so historical statistics cannot be independently recomputed
from this repository alone. The runner and analyzer below produce new captures.

## Reproduce the final comparison

Use Python 3.12+, kubectl and Helm, with your chosen Kubernetes context active.
The measured environment was an Apple Silicon 16 GiB host running a Linux
ARM64 Colima VM with four CPUs and 12 GiB RAM, k3s v1.33.4+k3s1 and
metrics-server. The deployment intentionally selects Linux ARM64; the pinned
CPU image is the tested artifact, not a claim of portability to other architectures.
The image reports vLLM 0.30.0. Internet access is needed for images, the Helm
chart and public model weights; no Hugging Face token was required.

The manifest pins SmolLM2 revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`:
BF16, context 1024, eight sequences, 256-token batches, 256 MiB KV cache,
one CPU, 2560 MiB memory request and 3 GiB limit per pod. KEDA 2.20.2 targets
three waiting requests per replica, min one/max three, with 300 s scale-down
stabilization. Prometheus 3.5.0 discovers each pod and scrapes every five seconds.
The Python scripts use only the standard library.

From the repository root, on a dedicated lab cluster:

```sh
kubectl apply -f k8s/vllm-deployment.yaml -f k8s/vllm-service.yaml
kubectl apply -f k8s/prometheus.yaml
helm repo add kedacore https://kedacore.github.io/charts
helm repo update kedacore
helm upgrade --install keda kedacore/keda --version 2.20.2 \
  --namespace keda --create-namespace -f k8s/keda-values.yaml --wait --timeout 5m
kubectl -n vllm-lab rollout status deployment/vllm --timeout=15m
kubectl -n vllm-lab rollout status deployment/prometheus --timeout=3m
kubectl apply -f k8s/keda-scaledobject.yaml
kubectl -n vllm-lab wait --for=condition=Ready scaledobject/vllm-waiting --timeout=60s
kubectl -n vllm-lab create configmap load-test \
  --from-file=load_test.py=load/load_test.py --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/load-generator.yaml
kubectl -n vllm-lab wait --for=condition=Ready pod/load-generator --timeout=3m
```

Do not reapply the deployment's `replicas: 1` during autoscaling measurements.
Service port-forward selects a single pod; run this workload inside the cluster.
Use fresh result directories for every run. The load pod has ephemeral storage
and a 24-hour lifetime; recreate it if it has completed.

```sh
kubectl -n vllm-lab annotate scaledobject vllm-waiting \
  autoscaling.keda.sh/paused-replicas='1' --overwrite
# Wait until desired AND Ready replicas are both one before starting.
kubectl -n vllm-lab get deployment vllm -w
# Stop watching with Ctrl-C once stable, then run the baseline.
kubectl -n vllm-lab exec load-generator -- env DURATION=300 CONCURRENCY=24 \
  RESULTS_DIR=/results/baseline python /scripts/load_test.py
kubectl -n vllm-lab annotate scaledobject vllm-waiting autoscaling.keda.sh/paused-replicas-
kubectl -n vllm-lab exec load-generator -- env DURATION=300 CONCURRENCY=24 \
  RESULTS_DIR=/results/autoscaled python /scripts/load_test.py
mkdir -p artifacts
kubectl -n vllm-lab cp load-generator:/results/baseline artifacts/baseline
kubectl -n vllm-lab cp load-generator:/results/autoscaled artifacts/autoscaled
python3 load/analyze_results.py artifacts/baseline
python3 load/analyze_results.py artifacts/autoscaled
```

Each run writes streaming timings, token counts, per-pod raw metrics,
replica status and CPU/memory samples. The analyzer derives queue mean,
client percentiles, time to three Ready replicas and per-pod completions.
Check telemetry errors, failures and sampled container restart counts before
accepting a run. Copy results before deleting the load pod.

Remove the lab resources when finished (this deletes ephemeral results and
Prometheus data; uninstall KEDA only if installed solely for this experiment):

```sh
kubectl delete -f k8s/keda-scaledobject.yaml
kubectl delete -f k8s/load-generator.yaml
kubectl -n vllm-lab delete configmap load-test
kubectl delete -f k8s/prometheus.yaml
kubectl delete -f k8s/vllm-service.yaml
kubectl delete -f k8s/vllm-deployment.yaml
helm uninstall keda --namespace keda
```

Helm may retain cluster-scoped KEDA CRDs after uninstall.
