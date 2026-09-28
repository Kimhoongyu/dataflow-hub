# Bucket names are global across NCP, so a random suffix avoids collisions.
resource "random_id" "bucket" {
  byte_length = 3
}

resource "ncloud_objectstorage_bucket" "uploads" {
  bucket_name = "${var.name}-uploads-${random_id.bucket.hex}"
}
