# EKS GPU experiment results — October 2, 2026

A controlled inference overload experiment on three pre-provisioned T4 GPU
nodes. Terraform fixes node capacity at three; KEDA changes only vLLM pods.
The baseline held one replica, then the identical workload ran with KEDA
resumed. These measurements are separate from the earlier local CPU experiment.

## Environment and method

- AWS EKS, Kubernetes 1.35; three on-demand `g4dn.xlarge` nodes, one T4 each.
- vLLM 0.11.2, `vllm/vllm-openai:v0.11.2`; observed image digest:
  `sha256:2c908d5a84ed251b6a17d179f42d06df1aff353007779ac5eecd8a0ea3fe9331`.
- `HuggingFaceTB/SmolLM2-135M-Instruct`, revision
  `12fd25f77366fa6b3b4b768ec3050bf629380bac`, served as `lab-small`, FP16.
- Context 1024, eight sequences, 256-token batches, 256 MiB KV cache;
  eager execution, prefix caching disabled. One GPU per pod; CPU request/limit
  2/3 cores, RAM request/limit 4/8 GiB. GPU sharing was not configured.
- Prometheus 3.5.0 discovers each pod, scraping every five seconds.
  KEDA 2.20.2 uses summed `vllm:num_requests_waiting`, target three waiting
  requests per replica, min one/max three, 300-second scale-down stabilization.
- 24 closed-loop clients, a 300-second dispatch window, exactly 700 input
  and 128 output tokens per request. Outstanding requests drain before exit.
  Token counts were verified for every successful request in both captures.
- Requests use fresh connections to the in-cluster Service; no port-forward.
  Baseline: KEDA paused at one replica. Autoscaled: pause removed.

Run labels: `eks-baseline-20261002T153844Z` and
`eks-autoscaled-20261002T162017Z`. These labels are client UTC start labels;
telemetry and request timestamps within each capture are elapsed seconds.

## Full-run comparison

| Measurement | Fixed one replica | KEDA enabled |
|---|---:|---:|
| Successful requests | 1072/1072 | 2246/2246 |
| Request failures | 0 | 0 |
| Maximum desired / Ready replicas | 1 / 1 | 3 / 3 |
| First sample with three Ready replicas | — | 81.08 s |
| Mean queue time | 4.49 s | 0.88 s |
| Mean client TTFT | 4.57 s | 0.96 s |
| Mean client E2E latency | 6.79 s | 3.22 s |
| P95 client TTFT | 4.67 s | 4.63 s |
| P95 client E2E latency | 6.89 s | 6.85 s |
| Estimated P95 queue time | 4.87 s | 4.04 s |
| Peak sampled waiting requests | 21 | 16 |
| Mean aggregate pod CPU | 0.97 cores | 2.83 cores |
| Peak aggregate pod CPU | 1.08 cores | 3.24 cores |
| Peak per-pod working-set RAM | 2253 MiB | 2943 MiB |
| Maximum sampled model-container restarts | 0 | 0 |
| Telemetry errors | 0 | 0 |
| Runner elapsed time, including drain/final observation | 316.10 s | 312.39 s |

Mean queue time fell **80.5%**, mean E2E latency fell **52.6%**, and the
same-concurrency dispatch window completed **2.10×** as many requests.
Full-run P95 latency barely changed.

## Capacity and trigger proof

[Scaling events](autoscaled/events.txt) record the KEDA-managed HPA selecting
three replicas because external metric `s0-prometheus` was above target.
The raw samples start at one desired/Ready replica and reach three Ready
replicas at 81.08 seconds. Samples record one GPU reservation per pod and
placement on three distinct nodes. Per-pod completion-counter deltas:

| Pod | Sanitized node alias | Completions | Maximum sampled restarts |
|---|---|---:|---:|
| `vllm-876cdb784-k5svg` | `gpu-node-1` | 991 | 0 |
| `vllm-876cdb784-rb7tv` | `gpu-node-2` | 618 | 0 |
| `vllm-876cdb784-l6qp5` | `gpu-node-3` | 637 | 0 |

The counts sum to 2246 and match successful client requests. The baseline
pod completed all 1072 requests with zero sampled restarts. Placement/restart
checks are retained in [baseline verification](baseline/verification.json)
and [autoscaled verification](autoscaled/verification.json).

The final [pod snapshot](autoscaled/pods-after.txt) was collected after the
run: scale-down had already removed one pod, leaving two. It is not the proof
of three replicas during load; use the time-series samples and counters.
Node instance type and allocatable GPU count were checked before the runs,
but a standalone before/after node inventory was not saved with these captures.
The captured node assignments establish three distinct serving nodes; fixed
node capacity is configured in Terraform. GPU utilization was not measured.

## Startup and interpretation

The measured scale-out used **cached container images**. The event capture
also contains an earlier scale-out whose image pulls took 6m19s and 6m32s;
those pods were subsequently deleted. During the measured run, both new
pods report that their image was already present. The 81-second result
includes new pod/model startup, not a first download of the 14 GB image.
Model caches are per-pod ephemeral; the original baseline pod was already warm.

For the 1942 requests started after three replicas became Ready, P95 TTFT
was 1.75 s and P95 E2E was 3.99 s. This subset supports improved latency after
usable capacity arrived; it does not replace the full-run comparison.

The evidence supports: queue growth triggered KEDA, additional GPU-backed
pods became Ready and served traffic through the Service, and average queue
and E2E latency improved. Startup-period requests kept full-run tail latency
high. CPU was below its three-core per-pod limit in this EKS run; the earlier
local CPU run did saturate CPU. Inference metrics expose queueing impact in
both environments. No CPU autoscaler comparison was performed.

## Measurement limits

Each scenario ran once. Fixed concurrency allows more requests when responses
become faster; this is not a fixed-arrival-rate throughput benchmark.
TTFT is time to first nonempty streamed text; client P95 uses nearest rank.
Queue means use server histogram sum/count deltas. Queue P95 interpolates
within a broad 2.5–5 s bucket and is approximate. Five-second samples and
metrics-server refresh intervals can miss short peaks. Restart claims apply
to sampled model container statuses. Events mix prior and measured activity,
and their `LAST SEEN` values are relative to the time they were collected.
No claim of a production outage, GPU saturation or a latency SLO is made.

## Evidence and reproducibility

- [Baseline summary](baseline/summary.json) and [analysis](baseline/analysis.json).
- [Autoscaled summary](autoscaled/summary.json) and [analysis](autoscaled/analysis.json).
- [EKS execution instructions](../k8s/README.md), [Terraform](../terraform/README.md),
  [load runner](../load/load_test.py), [analyzer](../load/analyze_results.py).
- Raw attachment: `eks-evidence-2026-10-02.tar.gz`; verify it with
  [the SHA-256 checksum](raw-archive.sha256).

The archive contains per-request timings/token usage, sampled per-pod metrics,
before/after metrics, summaries, analyses, verification records and events.
Private addresses and AWS identifiers are removed; node names are replaced
consistently. Kubernetes snapshots retain only measurement-relevant fields.
The original local captures are untouched. Re-running the existing analyzer
on the sanitized archive reproduced both original analyses exactly.

After downloading and extracting the release attachment:

```sh
sha256sum -c evidence/raw-archive.sha256
# macOS can use: shasum -a 256 -c evidence/raw-archive.sha256
tar -xzf eks-evidence-2026-10-02.tar.gz
python3 load/analyze_results.py eks-evidence-2026-10-02/baseline
python3 load/analyze_results.py eks-evidence-2026-10-02/autoscaled
```

## Historical local CPU evidence

<details>
<summary>Earlier ARM64 CPU measurements and investigation</summary>

### Local CPU experiment — September 28–29, 2026

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

### Usable-capacity proof

KEDA scaled 1 → 3 Ready replicas in **76 seconds** (first sampled at 76.18 s). Pod memory was approximately **2.7–2.9 GiB**: one snapshot recorded 2737, 2759, and 2884 MiB. Per-pod completion-counter increases during the autoscaled run:

- `vllm-dc6c588d8-zlbbv`: 53 completed requests.
- `vllm-dc6c588d8-vfzcn`: 25 completed requests.
- `vllm-dc6c588d8-64k6q`: 27 completed requests.

All three remained Ready with zero model-container restarts during the test. KEDA was resumed from the one-replica baseline; these replicas were added by the waiting-request trigger, not by manual scaling. The memory fit required a smaller model and a 12 GiB VM; three Qwen replicas did not pass.

Request failures: **zero** (65/65 baseline; 105/105 autoscaled). Model-container restarts: **zero** in both runs, verified from sampled container statuses. No telemetry errors were recorded.

### Interpretation

The scaler now adds usable serving capacity, and the Kubernetes Service distributes new requests to it. Average queue time and latency improved, and more requests completed under the same concurrency and dispatch duration. Overall p95 and maximum waiting depth did not improve dramatically: the run includes cold-start backlog, and existing queued requests stay on the original pod.

For the 75 requests started after all three replicas became Ready, p95 TTFT was 79.28 s and p95 E2E was 124.66 s. This subset is supplementary; it is not a replacement for the full-run comparison.

CPU was saturated per active pod, not low. Aggregate CPU rises as replicas add compute. This does not demonstrate that a properly normalized CPU dashboard would miss the overload, nor that a latency SLO has been met.

### Measurement limits

Queue p95 estimates interpolate within the same broad 60–120 s bucket in both runs; the apparent small difference is not precise. Client TTFT/E2E percentiles use individual streaming request timings. Mean queue time uses server histogram counter deltas. Metrics and CPU were sampled approximately every five seconds and can miss short peaks.

This is a fixed-concurrency closed-loop workload, not a fixed arrival rate: faster responses allow more requests. Baseline elapsed time including drain was 420.49 s; autoscaled elapsed time was 349.58 s. Each scenario ran once, on separate days, so these are descriptive lab results, not statistically controlled performance guarantees.

### Investigation history (separate configurations)

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

### Provenance

During repository cleanup, both final analyses were recomputed from the
original per-pod before/after metrics, sampled metrics and request records;
rounded values matched this report. Sampled model restart counts were zero.
Original run labels were `sustained-before` and `sustained-after`. Redundant
reports, raw captures, cluster dumps and intermediate manifests were removed
from the public tree after review. This document retains the validated
measurements and relevant historical findings; the original raw runs are
not included, so historical statistics cannot be independently recomputed
from this repository alone. The runner and analyzer below produce new captures.


</details>
