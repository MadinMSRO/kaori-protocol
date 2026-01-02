import os
import shutil

class StorageBackend:
    def save(self, file_bytes: bytes, filename: str) -> str:
        raise NotImplementedError

class LocalStorage(StorageBackend):
    def __init__(self, base_dir: str = "storage"):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        
    def save(self, file_bytes: bytes, filename: str) -> str:
        path = os.path.join(self.base_dir, filename)
        with open(path, "wb") as f:
            f.write(file_bytes)
        return path

# Default standard storage
# In production, swap with GCSStorage
import io

class GCSStorage(StorageBackend):
    def __init__(self, bucket_name: str):
        from google.cloud import storage
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        
    def save(self, file_bytes: bytes, filename: str) -> str:
        blob = self.bucket.blob(filename)
        blob.upload_from_file(io.BytesIO(file_bytes))
        return f"gs://{self.bucket.name}/{filename}"

if os.getenv("GCS_BUCKET_NAME"):
    storage = GCSStorage(os.getenv("GCS_BUCKET_NAME"))
else:
    storage = LocalStorage()
