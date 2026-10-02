variable "cluster_name" {
  type = string
}

variable "kubernetes_version" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "api_allowed_cidrs" {
  type = list(string)
}

variable "gpu_instance_type" {
  type = string
}

variable "node_group_size" {
  type = object({
    min     = number
    desired = number
    max     = number
  })
}
