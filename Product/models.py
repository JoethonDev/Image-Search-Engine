# product_service/models.py (or similar)
from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import List, Optional, Union
import base64
from datetime import datetime

# Input Models
class Merchant(BaseModel):
    merchant_id: int
    is_owner: bool

class ProductInput(BaseModel):
    en_name: str
    ar_name: str
    description: Optional[str] = None
    price: float = Field(..., gt=0) # Price must be positive
    # merchant_id: int
    images: List[Union[HttpUrl, bytes, str]] = Field(..., min_items=1) # Must have at least one variant
    color: str
    product_link: Optional[HttpUrl] = None

    @field_validator('images')
    def validate_image_format(cls, images):
        images_list = []
        for image_str in images:
            if "http" in image_str:
                images_list.append(image_str)
            else:
                images_list.append(base64.b64decode(image_str))
        return images_list

class AddProductsRequest(BaseModel):
    products: List[ProductInput]

class ProductUpdateInput(BaseModel):
    en_name: Optional[str] = None
    ar_name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)

    color: Optional[str] = None # Update variant color
    images: Optional[List[Union[HttpUrl, bytes, str]]] = None # Update variant images
    product_url: Optional[str] = None # Update variant link
    disabled: Optional[bool] = None # Allow disabling/enabling

    @field_validator('images')
    def validate_image_format(cls, images):
        images_list = []
        for image_str in images:
            if "http" in image_str:
                images_list.append(image_str)
            else:
                images_list.append(base64.b64decode(image_str))
        return images_list

import enum

# Define the Enum for allowed actions
class ProductAction(enum.Enum):
    like = "like"
    dislike = "dislike"
    netural = None

class ProductReact(BaseModel):
    action: ProductAction


# Output Models
class ProductOutput(BaseModel):
    product_id: int
    en_name: str
    ar_name: str
    description: Optional[str]
    price: float
    merchant_id: int
    color: Optional[str] # Remove it
    images: List[HttpUrl] # Assume we store URLs after processing/uploading
    product_url: Optional[HttpUrl]
    disabled: bool
    created_at: datetime
    updated_at: Optional[datetime]
    likes: int = 0
    dislikes: int = 0
    action: Optional[ProductAction] = None # User's specific action (like/dislike/None)
    ranking_score: Optional[float] = None # Added to ProductOutput

    class Config:
        from_attributes = True # Enable ORM mode
