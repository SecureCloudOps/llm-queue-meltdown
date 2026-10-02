# EKS infrastructure

Creates only a dedicated VPC and its networking, an EKS cluster, one GPU
managed node group, and required IAM. No Helm releases or application
workloads are managed here.

The network spans two supplied availability zones: two public subnets, two
private subnets, an internet gateway and one NAT gateway. Nodes have no
public IPs. One NAT keeps the lab simple but is a single point of failure
and may incur cross-AZ traffic charges. EKS creates its cluster security
group; the managed node group uses it without SSH access.

Defaults: Kubernetes 1.35, three on-demand `g4dn.xlarge` nodes, an AL2023
NVIDIA AMI, and an encrypted 80 GiB gp3 root disk per node. Min, desired and
max are fixed at three. Each node has one T4 GPU; one vLLM pod reserves that
GPU. KEDA changes only the vLLM replica count from one to three. No Cluster
Autoscaler or Karpenter is installed. All three nodes remain billable while
idle. Managed node-group updates can temporarily add replacement nodes;
avoid updates during measurements.
The cluster creator gets administrator access. Use a durable AWS identity.

The node role carries the standard worker, ECR pull and IPv4 CNI policies.
This minimal lab does not configure separate CNI workload identity; pods
that can reach instance metadata may obtain node-role credentials. IMDSv2
is required. No application AWS permissions are added.

## Configure and validate

Requires Terraform 1.6+, AWS credentials, and suitable GPU quotas and
capacity in both selected AZs. Region and AZs must match. Verify the chosen
Kubernetes version and instance availability in your account before applying.

Create a local, Git-ignored `terraform.tfvars` in this directory:

```hcl
aws_region         = "us-east-1"
availability_zones = ["us-east-1a", "us-east-1b"]
api_allowed_cidrs  = ["203.0.113.10/32"] # Replace with your real public IPv4/32.
```

The EKS API is accessible privately and publicly only from the supplied
CIDRs. Keep them current when your public IP changes. Choose a VPC CIDR
that does not overlap networks you intend to connect.

From the repository root:

```sh
terraform -chdir=terraform init
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform plan -out=eks.tfplan
```

Review the plan before running `terraform -chdir=terraform apply eks.tfplan`.
EKS, GPU instances, disks, NAT and public IPv4 addresses incur charges.
State is local and ignored by Git; retain it until teardown. Keep the provider
lock file in Git. After creation, use the `configure_kubectl` output with the
same AWS identity. Review `terraform -chdir=terraform plan -destroy` before
an explicitly authorized teardown with `terraform -chdir=terraform destroy`.

## Workload boundary

EKS bootstraps its default networking and DNS components. The NVIDIA device
plugin, metrics-server, Prometheus, KEDA and vLLM are separate workload setup.
The accelerated AMI includes GPU drivers; GPU scheduling still needs the
[NVIDIA device plugin](https://docs.aws.amazon.com/eks/latest/userguide/ml-eks-optimized-ami.html).

The [application setup](../k8s/README.md) uses an x86_64 GPU vLLM image and
one GPU per pod. The model and load-test protocol are retained; T4 uses FP16
instead of the local CPU run's BF16. Infrastructure capacity must be Ready
before the baseline starts. The EKS comparison and separate historical CPU results are documented in
`evidence/results.md`.
