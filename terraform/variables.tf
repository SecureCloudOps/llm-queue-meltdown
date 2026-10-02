variable "aws_region" {
  description = "AWS region for the lab; authentication uses the normal AWS credential chain."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "Name prefix for the dedicated EKS lab and its IAM roles."
  type        = string
  default     = "llm-queue-meltdown"
  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]{0,39}$", var.cluster_name))
    error_message = "Use a letter followed by up to 39 letters, digits or hyphens."
  }
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version; verify regional availability before planning."
  type        = string
  default     = "1.35"
  validation {
    condition     = can(regex("^1\\.[0-9]+$", var.kubernetes_version))
    error_message = "Use a Kubernetes minor version such as 1.35."
  }
}

variable "vpc_cidr" {
  description = "IPv4 VPC CIDR, split into four equal subnets across two AZs."
  type        = string
  default     = "10.42.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && can(cidrsubnet(var.vpc_cidr, 2, 3)) && try(tonumber(split("/", var.vpc_cidr)[1]) >= 16 && tonumber(split("/", var.vpc_cidr)[1]) <= 22, false)
    error_message = "Use a valid IPv4 VPC CIDR with a prefix from /16 to /22."
  }
}

variable "availability_zones" {
  description = "Two distinct AZs in aws_region with the selected GPU instance available."
  type        = list(string)
  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "Supply exactly two distinct availability zones."
  }
}

variable "api_allowed_cidrs" {
  description = "Trusted IPv4 CIDRs allowed to reach the public EKS API, usually your IP/32."
  type        = list(string)
  validation {
    condition     = length(var.api_allowed_cidrs) > 0 && alltrue([for cidr in var.api_allowed_cidrs : can(cidrnetmask(cidr)) && try(tonumber(split("/", cidr)[1]) >= 24, false)])
    error_message = "Supply at least one valid IPv4 CIDR restricted to /24 or narrower."
  }
}

variable "gpu_instance_type" {
  description = "x86_64 NVIDIA GPU instance type supported by the AL2023 NVIDIA EKS AMI."
  type        = string
  default     = "g4dn.xlarge"
  validation {
    condition     = can(regex("^(g4dn|g5|g6|g6e)\\.", var.gpu_instance_type))
    error_message = "Choose an x86_64 NVIDIA instance in the g4dn, g5, g6 or g6e family."
  }
}

variable "node_group_size" {
  description = "Pre-provisioned GPU capacity, fixed at three nodes for the pod-scaling experiment."
  type = object({
    min     = number
    desired = number
    max     = number
  })
  default = { min = 3, desired = 3, max = 3 }
  validation {
    condition = (
      var.node_group_size.min == 3 &&
      var.node_group_size.desired == 3 &&
      var.node_group_size.max == 3
    )
    error_message = "Keep min, desired and max at 3; only vLLM pods scale during this experiment."
  }
}

variable "tags" {
  description = "Additional tags applied to AWS resources."
  type        = map(string)
  default     = {}
}
