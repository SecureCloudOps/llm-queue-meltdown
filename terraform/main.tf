provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(var.tags, {
      Project   = var.cluster_name
      ManagedBy = "Terraform"
    })
  }
}

module "network" {
  source = "./modules/network"

  name               = var.cluster_name
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
}

module "eks" {
  source = "./modules/eks"

  cluster_name       = var.cluster_name
  kubernetes_version = var.kubernetes_version
  subnet_ids         = module.network.private_subnet_ids
  api_allowed_cidrs  = var.api_allowed_cidrs
  gpu_instance_type  = var.gpu_instance_type
  node_group_size    = var.node_group_size

  # Nodes need working outbound routes before bootstrap starts.
  depends_on = [module.network]
}
