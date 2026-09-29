# LLM queue meltdown

A CPU-backed vLLM experiment: sustained traffic → Kubernetes Service → vLLM
→ Prometheus → KEDA.

## Symptom

Inference latency rose while health checks remained green. A Ready pod was
accepting requests faster than it could serve them.

## Investigation

CPU correctly signaled saturation. vLLM metrics explained the inference-specific
impact through waiting requests and queue time, while streaming client timings
measured TTFT and E2E latency. Early scaling attempts requested
three replicas, but insufficient capacity left two Pending. Port-forward
traffic also targeted one pod and could not validate load balancing.

## Root cause

CPU capacity and the eight-sequence serving limit constrained throughput.
Readiness did not measure queue delay. The original Qwen configuration could
not fit three usable replicas; cache exhaustion and low-CPU overload were
not demonstrated.

## Remediation

Fit SmolLM2-135M-Instruct into a four-CPU, 12 GiB Linux ARM64 VM using BF16,
a 256 MiB KV cache and one CPU/3 GiB limit per pod. Scale from one to three
replicas using waiting requests, and route fresh connections through the
in-cluster Service. Both final runs used identical model and serving settings.

## Validation

With 24 concurrent clients, 700 input/128 output tokens and a five-minute
dispatch window:

| Measurement | One replica | KEDA enabled |
|---|---:|---:|
| Ready replicas | 1 | 3 within 76 s |
| Mean queue time | 84.70 s | 31.56 s |
| Mean E2E latency | 133.69 s | 72.96 s |
| P95 TTFT | 118.78 s | 116.15 s |
| Successful requests | 65/65 | 105/105 |

Pod memory was approximately 2.7–2.9 GiB. There were zero request failures
and zero model restarts. All three replicas served requests; CPU remained
saturated under load. [Measurements and reproduction steps](evidence/results.md).

## Limitation

Autoscaling reduced queueing and E2E latency, but cold-start tail latency
remained high. Existing queued requests stayed on the original pod. Each
scenario ran once; fixed concurrency permits more requests as latency falls,
so this is not a fixed-arrival-rate benchmark or proof of a latency SLO.
No CPU-based autoscaler was tested; these results do not establish that
queue-based scaling outperforms CPU-based scaling.
