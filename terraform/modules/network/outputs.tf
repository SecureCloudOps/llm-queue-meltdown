output "vpc_id" {
  value = aws_vpc.this.id
}

output "private_subnet_ids" {
  value = [for zone in var.availability_zones : aws_subnet.private[zone].id]
}
