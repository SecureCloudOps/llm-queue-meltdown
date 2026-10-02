data "aws_partition" "current" {}

resource "aws_iam_role" "cluster" {
  name = "${var.cluster_name}-cluster"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "eks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  # Only the standard networking/DNS components EKS bootstraps by default.
  bootstrap_self_managed_addons = true

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.api_allowed_cidrs
  }

  kubernetes_network_config {
    ip_family = "ipv4"
  }

  depends_on = [aws_iam_role_policy_attachment.cluster]
}

resource "aws_iam_role" "nodes" {
  name = "${var.cluster_name}-gpu-nodes"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

# CNI permissions use the node role in this minimal lab (no IRSA/add-on stack).
resource "aws_iam_role_policy_attachment" "nodes" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEC2ContainerRegistryPullOnly",
    "AmazonEKS_CNI_Policy",
  ])
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.value}"
}

resource "aws_launch_template" "gpu" {
  name_prefix = "${var.cluster_name}-gpu-"

  # EKS supplies the AMI, bootstrap data, instance profile and cluster SG.
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 80
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.cluster_name}-gpu" }
  }
}

resource "aws_eks_node_group" "gpu" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "gpu"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = var.subnet_ids
  version         = var.kubernetes_version
  ami_type        = "AL2023_x86_64_NVIDIA"
  instance_types  = [var.gpu_instance_type]
  capacity_type   = "ON_DEMAND"

  launch_template {
    id      = aws_launch_template.gpu.id
    version = aws_launch_template.gpu.latest_version
  }

  scaling_config {
    min_size     = var.node_group_size.min
    desired_size = var.node_group_size.desired
    max_size     = var.node_group_size.max
  }

  update_config {
    max_unavailable = 1
  }

  labels = { workload = "inference" }

  # No GPU taint: this is the only node group and also hosts cluster services.
  depends_on = [aws_iam_role_policy_attachment.nodes]
}
