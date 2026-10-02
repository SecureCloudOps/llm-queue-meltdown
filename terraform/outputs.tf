output "vpc_id" {
  description = "Dedicated lab VPC."
  value       = module.network.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnets used by EKS and its GPU nodes."
  value       = module.network.private_subnet_ids
}

output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "gpu_node_group_name" {
  description = "Managed GPU node group name."
  value       = module.eks.node_group_name
}

output "configure_kubectl" {
  description = "Run with the same AWS identity that created the cluster."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}
