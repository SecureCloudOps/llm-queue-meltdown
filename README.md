# LLM queue meltdown

A measured inference overload experiment on AWS EKS:
traffic → Service → GPU-backed vLLM → Prometheus → KEDA → more serving pods.

Start with the [Kubernetes manifests](k8s/), run the [load test](load/load_test.py), then review the [validated results](evidence/results.md).

## Symptom

One healthy vLLM replica accumulated up to 21 waiting requests under 24-client
load. Mean queue time reached 4.49 s and mean E2E latency reached 6.79 s.

## Investigation

Streaming client timings and per-pod vLLM metrics quantified queue delay,
TTFT and E2E latency. CPU averaged 0.97 cores against a three-core pod limit;
GPU utilization was not measured. The earlier local CPU experiment saturated
CPU too; inference metrics explained its queueing impact. CPU was not shown
to be a bad signal, and no CPU autoscaler comparison was performed.

## Root cause

A single serving replica had insufficient capacity for the offered concurrency,
even though readiness stayed green. The EKS run demonstrates queueing pressure;
it does not isolate GPU saturation as the cause.

## Remediation

[Terraform](terraform/) pre-provisions three `g4dn.xlarge` T4 nodes. Each vLLM
pod reserves one GPU. KEDA scales only pods from one to three using Prometheus
waiting-request metrics; the Service distributes fresh request connections.
Both runs used the same SmolLM2 model, FP16 settings, 24 clients, 700 input/128
output tokens and a five-minute dispatch window.

## Validation

| Measurement | One replica | KEDA enabled |
|---|---:|---:|
| Maximum Ready replicas | 1 | 3 at 81.08 s |
| Mean queue time | 4.49 s | 0.88 s |
| Mean E2E latency | 6.79 s | 3.22 s |
| P95 TTFT | 4.67 s | 4.63 s |
| P95 E2E latency | 6.89 s | 6.85 s |
| Successful requests | 1072/1072 | 2246/2246 |

Mean queue time fell **80.5%** and mean E2E fell **52.6%**. All three pods served
requests on distinct GPU nodes, with zero request failures, zero sampled model
restarts and no reported telemetry errors. [Evidence and methodology](evidence/results.md).

## Limitation

Full-run tail latency barely improved. Requests started after three replicas
became Ready had P95 TTFT/E2E of 1.75/3.99 s, but that is a different subset.
The 81-second scale-out reused cached images and still included model startup;
first image pulls previously took over six minutes. Each scenario ran once,
and fixed concurrency permits more requests as latency falls. Historical CPU
results are retained separately in the evidence report.
