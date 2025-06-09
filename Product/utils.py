# product_service/utils.py (or similar)
from typing import List
from sqlalchemy.orm import Session
import httpx
import re
import webcolors
import boto3 # type: ignore
from database import Color
import math
from config import settings
import time

# Cloudflare R2 Configuration
# ACCOUNT_ID = "YOUR_CLOUDFLARE_ACCOUNT_ID"  # Replace with your Cloudflare Account ID
ACCESS_KEY_ID = "64cd3d970efe7e7be0494956133340d8"  # Replace with your Access Key ID
SECRET_ACCESS_KEY = "daa1b7de184c4a802ab28d321908530d235aaea738bf927addcaba0baf4f3116"  # Replace with your Secret Access Key
BUCKET_NAME = "image-search"  # Replace with your R2 bucket name
TEMP_BUCKET_NAME = "temp-search-images"  # Replace with your R2 bucket name
ENDPOINT_URL = f"https://da59dca47179969defd66c61b710bbdb.r2.cloudflarestorage.com"
PUBLIC_URL = "https://pub-81f566f3e9f24e02ae2761612f9e8a18.r2.dev"

# --- Normalization Placeholders ---
def normalize_name(name: str, remove_words: List[str] = []) -> str:
    """
    Normalizes a name by converting it to lowercase, removing numbers,
    special characters (except ' and - after t), and specified words.

    Args:
        name: The name to normalize.
        remove_words: A list of words to remove from the name.

    Returns:
        The normalized name.
    """
    name = name.lower()
    name = re.sub(r'\d+', '', name)  # Remove numbers
    name = re.sub(r"[^a-zA-Z\u0621-\u064A\s'-]", '', name)  # Remove special characters except ' and - after t
    name = re.sub(r"t-", "t-", name) #keep t-
    name = re.sub(r"s'", "s'", name) #keep s'

    for word in remove_words:
        name = re.sub(r'\b' + re.escape(word) + r'\b', '', name)

    return ' '.join(name.split())  # Remove extra spaces

def normalize_description(description: str) -> str:
    """
    Normalizes a description by converting it to lowercase and removing numbers.

    Args:
        description: The description to normalize.

    Returns:
        The normalized description.
    """
    description = description.lower()
    description = re.sub(r'\d+', '', description)
    return ' '.join(description.split()) #remove extra spaces


def normalize_color(color: str) -> tuple:
    try:
        return webcolors.name_to_rgb(color.lower())
    except ValueError:
        return None

def color_distance(rgb1, rgb2):
    r1, g1, b1 = rgb1
    r2, g2, b2 = rgb2
    return math.sqrt((r1 - r2)**2 + (g1 - g2)**2 + (b1 - b2)**2)

def map_color_from_db(incoming_color_name, db: Session, max_distance=50):
    incoming_rgb = normalize_color(incoming_color_name)
    if not incoming_rgb:
        return None

    nearest_color_id = -1
    min_distance = float('inf')

    db_colors = db.query(Color).all() # Fetch your 10 main colors

    for db_color in db_colors:
        stored_rgb = normalize_color(db_color.color) # Assuming RGB stored as separate columns
        if not stored_rgb :
            continue
        distance = color_distance(incoming_rgb, stored_rgb)
        if distance < min_distance:
            min_distance = distance
            nearest_color_id = db_color.color_id

    if min_distance <= max_distance:
        return nearest_color_id
    else:
        return None

# --- Image Handling Placeholder ---
async def download_image(url: str, client: httpx.AsyncClient) -> bytes:
    try:
        response = await client.get(url, timeout=15.0)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"ERROR downloading image {url}: {e}")
        raise ValueError(f"Failed to download image: {url}") from e
    
def _upload_to_s3(image: bytes, key: str) :
    client = get_r2_client()
    try:
        client.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=image,
            ContentType="image/jpeg"
        )
        # print(f"File '{local_file_path}' uploaded to R2 as '{r2_object_key}'")
        return f"{PUBLIC_URL}/{key}" #returning the created url.
    except Exception as e:
        print(f"Error uploading to R2: {e}")
        return None

def _upload_to_temp_s3(image: bytes, key: str) :
    client = get_r2_client()
    try:
        client.put_object(
            Bucket=TEMP_BUCKET_NAME,
            Key=key,
            Body=image,
            ContentType="image/jpeg"
        )
        # print(f"File '{local_file_path}' uploaded to R2 as '{r2_object_key}'")
        return f"{PUBLIC_URL}/{key}" #returning the created url.
    except Exception as e:
        print(f"Error uploading to R2: {e}")
        return None
    
def _delete_from_s3(image_url: str) :
    client = get_r2_client()
    if BUCKET_NAME not in image_url:
        return True
    object_key = image_url.split(f"{BUCKET_NAME}/")[1]
    try:
        response = client.delete_object(Bucket=BUCKET_NAME, Key=object_key)
        print(f"Object '{object_key}' deleted from R2. Response: {response}")
        return True
    
    except Exception as e:
        print(f"Error deleting object '{object_key}' from R2: {e}")
        return False
        

# --- AI Service Call Placeholder ---
async def _call_ai_service(endpoint_url: str, data: dict, client: httpx.AsyncClient) -> dict:
    """Generic helper to call an AI endpoint."""
    try:
        # Adjust method, headers, data format based on each AI service needs
        # Handle multipart/form-data if sending files directly
        headers = {
            "Authorization" : settings.MODEL_TOKEN
        }
        start_time = time.time()
        response = await client.post(endpoint_url, json=data, headers=headers, timeout=90.0) # Longer timeout for AI
        print(f"Endpoint : {endpoint_url} has taken : {time.time() - start_time}")
        response.raise_for_status()
        return response.json() # Assuming AI services return JSON
    except Exception as e:
        print(f"ERROR calling AI service {endpoint_url}: {e}")
        # Decide on error handling: raise, return None, return default?
        raise ValueError(f"AI service call failed: {endpoint_url}") from e

# --- R2 Client ---
def get_r2_client():
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY_ID,
        aws_secret_access_key=SECRET_ACCESS_KEY,
        region_name="auto"  # Cloudflare R2 uses 'auto'
    )

    return s3

# --- DB Helpers ---
async def get_or_create_color(db: Session, normalized_color: str) -> Color:
    color_obj = db.query(Color).filter(Color.color == normalized_color).first()
    if not color_obj:
        color_obj = Color(color=normalized_color)
        db.add(color_obj)
        # Consider commit strategy - maybe commit separately or rely on main commit
        try:
            db.flush() # Flush to get ID without full commit if needed elsewhere soon
            db.refresh(color_obj) # Ensure we get the ID back
        except Exception as e:
             db.rollback() # Rollback if unique constraint fails etc.
             # It might already exist due to concurrent request, try fetching again
             color_obj = db.query(Color).filter(Color.color == normalized_color).first()
             if not color_obj: # If still not found, raise the original error
                 raise e

    return color_obj