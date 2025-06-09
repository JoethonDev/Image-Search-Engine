import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    # ORIGIN
    ORIGIN_HOST: str = os.environ.get("ORIGIN_HOST", "http://localhost:8000")

    # Service URLs
    OBJECT_DETECTION_ENDPOINT: str = os.environ.get("OBJECT_DETECTION_ENDPOINT", "https://8000-dep-01jvqca946fhmtbw99w37fvba8-d.cloudspaces.litng.ai/crop-images")
    CLIP_ENDPOINT: str = os.environ.get("OBJECT_DETECTION_ENDPOINT", "https://8000-dep-01jvqca946fhmtbw99w37fvba8-d.cloudspaces.litng.ai/combined-embedding")

    # R2 Bucket
    ACCESS_KEY_ID: str = os.environ("ACCESS_KEY_ID", "02ae896e2d9d616f2974c1c7aa58606c")  
    SECRET_ACCESS_KEY: str = os.environ("SECRET_ACCESS_KEY", "169a80861b77e1c5d3186725a7687bb9c9c1cd4c11d9ae06eb304af8376cc9f9")  
    BUCKET_NAME: str = os.environ("BUCKET_NAME", "image-search")  
    ENDPOINT_URL: str = os.environ("ENDPOINT_URL", "https://5e9ec5b566e9703fb3f6f8a502964765.r2.cloudflarestorage.com")  

    # AI Token
    # MODEL_TOKEN=os.environ.get("MODEL_TOKEN", "Bearer a80aed3e-48e5-4ad6-9ca5-41824c24fc6a")

    # Qdrant Cred
    QDRANT_ENDPOINT=os.environ("QDRANT_ENDPOINT", "https://a360dba7-56d4-4733-b614-6a0dded8bf31.europe-west3-0.gcp.cloud.qdrant.io")
    QDRANT_KEY=os.environ("QDRANT_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.uB0vtG4DBlmdvLAffcMaQP-twmmSUnfOtjVH_ZJF3OQ")
    QDARNT_COLLECTION=os.environ("QDARNT_COLLECTION", "products")

settings = Settings()