from fastapi import APIRouter, Depends, HTTPException, status, Query, Header, Path
from typing import List, Optional

import models, service, dependencies # Adjust imports as needed

router = APIRouter(
    prefix="/products", # Base prefix for product-related routes
    tags=["Products & Variants"],
    # Add authentication dependency for all routes if needed,
    # or apply selectively per route
    # dependencies=[Depends(dependencies.get_current_account)]
)

USER_HEADER = "X-USER-ID"

@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    # Define a simple response or a more detailed one if needed
    response_model=dict # Example: {"message": "...", "created_product_ids": [...]}
)
async def add_new_products(
    request_body: models.AddProductsRequest,
    product_service: service.ProductService = Depends(dependencies.get_product_service),
    merchant_id: int = Header(..., alias=USER_HEADER)
):
    """
    Add one or more new products with their variants.
    Requires merchant authentication.
    Triggers normalization and AI processing pipeline.
    """

    try:
        if not merchant_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str("Header is missing"))
        created_ids = await product_service.add_products(request_body.products, merchant_id)
        return {
            "message": f"Successfully added {len(created_ids)} products.",
            "created_product_ids": created_ids
            }
    except ValueError as ve: # Catch specific validation errors from service layer if defined
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except HTTPException as he: # Re-raise HTTP exceptions from service layer
        raise he
    except Exception as e: # Catch unexpected errors
        print(f"ERROR in add_new_products route: {e}") # Log the error
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred while adding products.")

@router.get(
    "/",
    response_model=List[models.ProductOutput] # Assuming ProductOutput has variants nested
)
async def get_merchant_products(
    skip: int = 0,
    limit: int = 50,
    product_service: service.ProductService = Depends(dependencies.get_product_service),
    user_id: int = Header(..., alias=USER_HEADER)
):
    """
    Retrieve products belonging to the authenticated merchant, with pagination.
    """
    # print(user_id)
    products = await product_service.get_products_by_merchant(
        merchant_id=user_id, is_owner=True, skip=skip, limit=limit
    )
    # Pydantic should handle conversion from SQLAlchemy objects due to Config.from_attributes = True
    return products

@router.get(
    "/{merchant_id}", # Second path definition: merchant_id from URL path
    response_model=List[models.ProductOutput]
)
async def get_store_products(
    merchant_id: int,
    skip: int = 0,
    limit: int = 50,
    product_service: service.ProductService = Depends(dependencies.get_product_service),
    user_id: int = Header(None, alias=USER_HEADER)
):
    """
    Retrieve products belonging to the authenticated merchant, with pagination.
    """
    is_owner = False
    if not merchant_id or merchant_id == user_id:
        is_owner = True
    products = await product_service.get_products_by_merchant(
        merchant_id=merchant_id, is_owner=is_owner, skip=skip, limit=limit
    )
    # Pydantic should handle conversion from SQLAlchemy objects due to Config.from_attributes = True
    return products


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_200_OK, # Or 204 No Content
    response_model=dict # Example: {"detail": "..."}
)
async def delete_single_product(
    product_id: int,
    product_service: service.ProductService = Depends(dependencies.get_product_service),
    merchant_id: int = Header(..., alias=USER_HEADER)
):
    """
    Delete a product and all its associated variants.
    Requires ownership by the authenticated merchant.
    """
    try:
        result = await product_service.delete_product(product_id, merchant_id)
        return result # Return detail message from service
    except HTTPException as he:
        raise he # Propagate 403/404 from service
    except Exception as e:
        print(f"ERROR in delete_single_product route for ID {product_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete product.")


@router.put(
    "/{variant_id}",
    response_model=models.ProductOutput # Return detailed variant info
)
async def update_single_variant(
    variant_id: int,
    update_data: models.ProductUpdateInput,
    product_service: service.ProductService = Depends(dependencies.get_product_service),
    merchant_id: int = Header(..., alias=USER_HEADER)
):
    """
    Update details of a specific product variant.
    Requires ownership by the authenticated merchant.
    Triggers AI pipeline rerun only if images/links change.
    """
    try:
        updated_variant = await product_service.update_product_variant(
            variant_id, update_data, merchant_id
        )
        # Need to map the updated SQLAlchemy variant object to the Pydantic output model
        # This might require joining Product and Color again if not eager loaded in update method
        # Or adjust the service method to return data suitable for the model directly
        # Simplified mapping (assuming direct attribute access works with from_attributes):
        # Manual mapping might be safer:
        return updated_variant
    except HTTPException as he:
        raise he
    # except Exception as e:
    #     print(f"ERROR in update_single_variant route for ID {variant_id}: {e}")
    #     raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update product variant.")
    finally:
            pass

# Can Access by any authenticated!
@router.get(
    "/bulk/",
    response_model=List[models.ProductOutput]
)
async def get_variants_bulk(
    # Use Query for list parameters
    variant_id: Optional[List[int]] = Query(default=[], description="List of variant int to fetch"),
    product_service: service.ProductService = Depends(dependencies.get_product_service),
    user_id: Optional[int] = Header(None, alias=USER_HEADER)
):
    """
    Retrieve full details for multiple product variants by their int.
    Typically used by the Search Service after getting IDs from vector search.
    """
    if not variant_id:
        return [] # Return empty list if no IDs provided

    results = await product_service.get_variants_by_ids(variant_id, user_id)
    return results

# Product Like/Dislike
@router.post("/{product_id}/react", status_code=status.HTTP_204_NO_CONTENT)
async def react_to_product(
    react: models.ProductReact,
    user_id: int = Header(..., alias=USER_HEADER),
    product_id: int = Path(..., alias="product_id"),
    product_service: service.ProductService = Depends(dependencies.get_product_service)
):
    try:
        result = await product_service.react_product(product_id, user_id, react)
    
    except HTTPException as he:
        raise he
    except Exception :
        raise HTTPException(status_code=500, detail="Can not save react to product!")
    