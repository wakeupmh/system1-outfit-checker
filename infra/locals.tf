resource "random_password" "demo_key" {
  length  = 24
  special = false
}

resource "random_password" "admin_key" {
  length  = 32
  special = false
}

resource "random_id" "site" {
  byte_length = 4
}

locals {
  demo_key        = coalesce(var.demo_key, random_password.demo_key.result)
  admin_key       = coalesce(var.admin_key, random_password.admin_key.result)
  hosting_site_id = coalesce(var.hosting_site_id, "${var.name}-${random_id.site.hex}")
  hosting_origins = [
    "https://${local.hosting_site_id}.web.app",
    "https://${local.hosting_site_id}.firebaseapp.com",
  ]
  allowed_origins = concat(local.hosting_origins, ["http://localhost:9000"])
}
