# EKS GPU experiment

Terraform provisions three on-demand `g4dn.xlarge` nodes before testing.
Each node has one NVIDIA T4; each vLLM pod requests and limits
`nvidia.com/gpu: 1`. Without GPU sharing, three replicas occupy three nodes.
KEDA scales only the Deployment from 1 to 3 using Prometheus waiting-request
metrics. There is no node autoscaler and no GPU sharing configuration.

The hypothesis is: queue builds → Prometheus observes it → KEDA requests
replicas → new GPU-backed pods become Ready → the Service sends new requests
to them → queue time and E2E latency fall. Existing queued requests do not
migrate. Prove each step with measurements; scale-out alone is not a latency result.

## Configuration

- Infrastructure: [Terraform](../terraform/README.md), fixed 3/3/3 node count.
- vLLM: version 0.11.2 GPU image, same pinned SmolLM2-135M model and API name.
  This [version documents T4 support](https://docs.vllm.ai/en/v0.11.2/getting_started/installation/gpu/).
- T4 uses FP16; CPU-only allocator and thread settings were removed.
  Context 1024, eight sequences, 256-token batches and 256 MiB KV cache remain.
  Prefix caching is disabled so repeated trials do not reuse previous prompts.
- Per pod: one GPU, CPU request/limit 2/3 cores, RAM request/limit 4/8 GiB.
- Prometheus scrapes every five seconds. KEDA targets three waiting requests
  per replica with a five-minute scale-down stabilization window.
- NVIDIA device plugin v0.17.1 advertises GPUs supplied by the AL2023 NVIDIA
  driver/runtime. Its kubelet socket mount is required; no GPU Operator is used.

The T4 runtime and before/after experiment were validated on October 2, 2026.
[Results and limits](../evidence/results.md) include the separate historical CPU
measurements. Compare the EKS scenarios to each other; image/version, hardware
and dtype differ from the earlier CPU run.

## Deployment order (for a later authorized run)

Run from the repository root after provisioning. Select the intended EKS
context explicitly; all commands below use `EKS_CONTEXT`.

```sh
export EKS_CONTEXT='your-eks-context'
kubectl --context "$EKS_CONTEXT" get nodes -l eks.amazonaws.com/nodegroup=gpu
kubectl --context "$EKS_CONTEXT" wait --for=condition=Ready node \
  -l eks.amazonaws.com/nodegroup=gpu --timeout=10m
kubectl --context "$EKS_CONTEXT" apply -f k8s/nvidia-device-plugin.yaml
kubectl --context "$EKS_CONTEXT" -n kube-system rollout status \
  daemonset/nvidia-device-plugin --timeout=5m
kubectl --context "$EKS_CONTEXT" get nodes -l eks.amazonaws.com/nodegroup=gpu \
  -o 'custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'
```

Before continuing, require exactly three Ready nodes with one allocatable GPU
per node. Do not install a second device plugin if one already exists.
Install metrics-server only if the cluster does not already provide it:

```sh
helm upgrade --install metrics-server metrics-server \
  --repo https://kubernetes-sigs.github.io/metrics-server/ --version 3.13.0 \
  --kube-context "$EKS_CONTEXT" --namespace kube-system --wait
kubectl --context "$EKS_CONTEXT" top nodes
kubectl --context "$EKS_CONTEXT" apply -f k8s/vllm-deployment.yaml -f k8s/vllm-service.yaml
kubectl --context "$EKS_CONTEXT" apply -f k8s/prometheus.yaml
helm upgrade --install keda keda --repo https://kedacore.github.io/charts \
  --version 2.20.2 --kube-context "$EKS_CONTEXT" --namespace keda \
  --create-namespace -f k8s/keda-values.yaml --wait --timeout 5m
kubectl --context "$EKS_CONTEXT" -n vllm-lab rollout status deployment/vllm --timeout=20m
kubectl --context "$EKS_CONTEXT" -n vllm-lab rollout status deployment/prometheus --timeout=3m
kubectl --context "$EKS_CONTEXT" apply -f k8s/keda-scaledobject.yaml
kubectl --context "$EKS_CONTEXT" -n vllm-lab wait \
  --for=condition=Ready scaledobject/vllm-waiting --timeout=60s
kubectl --context "$EKS_CONTEXT" -n vllm-lab create configmap load-test \
  --from-file=load_test.py=load/load_test.py --dry-run=client -o yaml | \
  kubectl --context "$EKS_CONTEXT" apply -f -
kubectl --context "$EKS_CONTEXT" apply -f k8s/load-generator.yaml
kubectl --context "$EKS_CONTEXT" -n vllm-lab wait --for=condition=Ready \
  pod/load-generator --timeout=3m
```

Do not apply the entire directory blindly: the ScaledObject requires KEDA CRDs.
Do not reapply the Deployment's one-replica setting during a measurement.

## Same-load baseline and scale-out

Start with the existing 24-client, 300-second, 700-input/128-output-token
protocol. The small model may be too fast on T4 to sustain a queue. If so,
report that result, calibrate concurrency in a separate pilot (runner supports
1–32), then repeat both scenarios with identical settings. Do not report
improvement or the CPU run's 76-second scale-out time without new evidence.

```sh
kubectl --context "$EKS_CONTEXT" -n vllm-lab annotate scaledobject vllm-waiting \
  autoscaling.keda.sh/paused-replicas='1' --overwrite
# Require one desired/Ready vLLM replica before starting; stop watching with Ctrl-C.
kubectl --context "$EKS_CONTEXT" -n vllm-lab get deployment vllm -w
mkdir -p artifacts
kubectl --context "$EKS_CONTEXT" get nodes -o json > artifacts/eks-nodes-before.json
kubectl --context "$EKS_CONTEXT" -n vllm-lab exec load-generator -- \
  env DURATION=300 CONCURRENCY=24 RESULTS_DIR=/results/eks-baseline python /scripts/load_test.py
kubectl --context "$EKS_CONTEXT" -n vllm-lab annotate scaledobject vllm-waiting \
  autoscaling.keda.sh/paused-replicas-
kubectl --context "$EKS_CONTEXT" -n vllm-lab exec load-generator -- \
  env DURATION=300 CONCURRENCY=24 RESULTS_DIR=/results/eks-autoscaled python /scripts/load_test.py
kubectl --context "$EKS_CONTEXT" -n vllm-lab get events --sort-by=.lastTimestamp \
  > artifacts/eks-events.txt
kubectl --context "$EKS_CONTEXT" get nodes -o json > artifacts/eks-nodes-after.json
kubectl --context "$EKS_CONTEXT" -n vllm-lab cp \
  load-generator:/results/eks-baseline artifacts/eks-baseline
kubectl --context "$EKS_CONTEXT" -n vllm-lab cp \
  load-generator:/results/eks-autoscaled artifacts/eks-autoscaled
python3 load/analyze_results.py artifacts/eks-baseline
python3 load/analyze_results.py artifacts/eks-autoscaled
```

Use fresh result directories for repeat runs. Do not use Service port-forward
for the load test: it selects one backing pod. The existing runner uses fresh
in-cluster Service connections and per-pod metrics.

Validate: all three nodes pre-existed, KEDA events name the external metric,
Ready pods increase from one to three on distinct nodes, each pod's completion
counter increases, telemetry is complete, request failures and model restarts
are zero, and full-run queue/latency statistics improve. Sampled pod records
include node placement and restart counts. CPU telemetry measures host CPU,
not GPU utilization. Image pulls/model downloads can still cause cold starts
on pre-provisioned nodes; keep cache conditions consistent and report them.
Keep new EKS results separate from the historical report until validated.

For teardown later, remove application resources and Helm releases before
Terraform destroys the infrastructure. Do not remove shared cluster add-ons.
The measured EKS runs used this setup; repeat runs require new result directories.
