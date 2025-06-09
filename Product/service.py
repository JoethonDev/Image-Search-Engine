# product_service/service.py (or similar)
import asyncio
from sqlalchemy.orm import Session, aliased
from sqlalchemy import func, case
from sqlalchemy.sql import expression
from sqlalchemy.dialects.postgresql import insert as pg_insert, ENUM as PG_ENUM # For upserting embeddings potentially
from fastapi import Depends, HTTPException, status # Assuming usage within FastAPI routes
from qdrant_client import QdrantClient, models as qdrant_models
import httpx
import uuid
from typing import List, Dict, Any
import base64

import models, database, utils
from config import settings # Assuming settings has AI endpoint URLs


class ProductService:
    def __init__(self, db: Session, http_client: httpx.AsyncClient, qdrant: QdrantClient):
        self.db = db
        self.client = http_client # HTTP client for downloads and AI calls
        self.qdrant = qdrant

    def get_product(self, product_id: int, merchant_id: int = -1) -> database.Product:
        # Fetch variant, check ownership, update 'disabled' flag
        variant = self.db.query(database.Product).filter(database.Product.product_id == product_id).first()
        # print(f"Product id : {product_id} with product value : {variant}")
        if not variant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")
        if merchant_id != -1 and variant.merchant_id != merchant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this variant.")
        
        return variant


    def build_images_urls(self, images: List, image_name: str = None):
        processed_image_urls = []
        processed_temp_image_urls = []
        original_image_index = 0
        image_prefix = str(uuid.uuid4()) + "-".join(image_name.split(" "))

        for img_input in images:
            # --- Handle Images & Schedule AI Tasks ---
            if isinstance(img_input, str):
                processed_image_urls.append(img_input)
                processed_temp_image_urls.append(img_input)

            else: 
                #image uploaded to S3, get URL
                image_key = f"{image_prefix}/{original_image_index}.jpg"
                final_image_url = utils._upload_to_s3(img_input, image_key)
                temp_image_url = utils._upload_to_temp_s3(img_input, image_key)
                processed_image_urls.append(final_image_url)
                processed_temp_image_urls.append(image_key)
            
            original_image_index += 1

        return processed_image_urls, processed_temp_image_urls

    async def add_products(self, products_input: List[models.ProductInput], merchant_id: int):
        new_db_products = []
        tasks_to_run = [] # For AI processing
        product_index = 0

        for product_in in products_input:
            # --- Normalize Product Level Data ---
            norm_en_name = utils.normalize_name(product_in.en_name)
            norm_ar_name = utils.normalize_name(product_in.ar_name)
            norm_desc = utils.normalize_description(product_in.description) if product_in.description else norm_en_name
            color_id = utils.map_color_from_db(product_in.color, self.db)
            # print(f"Color id : {color_id}")

            # --- Create Product DB Object (don't add to session yet) ---
            db_product = database.Product(
                en_name=norm_en_name,
                ar_name=norm_ar_name,
                description=norm_desc, # Store normalized or original? Decide. Storing normalized might be better.
                price=product_in.price,
                merchant_id=merchant_id,
                color_id=color_id,
                product_url=product_in.product_link
            )
            # Add to list to track which product corresponds to which variants later
            new_db_products.append(db_product)
            
            # URLs to store in DB eventually
            processed_image_urls, temp_urls = self.build_images_urls(product_in.images, norm_en_name)


            db_product.images = processed_image_urls
            # Schedule AI processing task for this image
            ai_task_data = {
                "images_url": temp_urls,
                "norm_en_name": norm_en_name,
                # "needs_desc_generation": norm_desc is None, # Flag if description needed
                "product_index" : product_index
            }
            product_index += 1
            tasks_to_run.append(self._process_image_with_ai(ai_task_data))


        # --- Run AI Tasks Concurrently ---
        # Process all images for all products/variants concurrently
        # batch_size = 32
        embeddings_to_store = {} # Store embeddings keyed by variant_id

        ai_results = await asyncio.gather(*tasks_to_run)

        # --- Process AI Results and Prepare Final DB Objects ---
        for result in ai_results:
            if isinstance(result, Exception):
                print(f"ERROR processing AI task: {result}")
                # Handle failed AI tasks - maybe skip embedding? Log?
            elif result: # Check if result is not None or empty
                product_index = result.get("product_index")
                embedding = result.get("embedding")
                generated_desc = result.get("generated_description")

                if embedding:
                    embeddings_to_store[product_index] = {
                        "embedding" : embedding,
                        "product_id" : None
                    }
                else:
                    print(f"Product : {product_index} has error in embeddings!")


        # --- Create DB Objects and Add to Session ---
        try:

            # Add products into session commit
            self.db.add_all(new_db_products)
            # --- Commit Transaction ---
            self.db.commit()
            print(f"SUCCESS: Added {len(new_db_products)} products")

            # Refresh objects to get IDs, defaults, etc.
            for p in new_db_products:
                self.db.refresh(p)

            # print(f"Embeddings : {embeddings_to_store}")
            # print(f"Stored : {new_db_products}")
            embeddings_as_points = []
            for index in range(len(new_db_products)):
                print(f"Lengths of embeddings : {len(embeddings_to_store[index]['embedding'])}")
                # print(f"embeddings : {embeddings_to_store[index]['embedding']}")
                embeddings_as_points.append(
                    qdrant_models.PointStruct(
                        id=new_db_products[index].product_id,
                        vector=embeddings_to_store[index]['embedding'],
                        payload={
                            "color" : products_input[index].color,
                            "price" : products_input[index].price
                        }
                    )
                )

            # Add Qdrant Connection to update embeddings
            print(f"INFO: Upserting {len(embeddings_as_points)} points to Qdrant collection '{settings.QDRANT_COLLECTION}'...")
            try:
                # Use upsert for idempotency
                self.qdrant.upsert(
                    collection_name=settings.QDRANT_COLLECTION,
                    points=embeddings_as_points,
                    wait=True # Wait for operation to complete for consistency
                )
                print(f"SUCCESS: Upserted points to Qdrant.")
            except Exception as e:
                print(f"ERROR: Failed to upsert points to Qdrant: {e}")
                # Critical decision: What to do if Qdrant fails?
                # Products are already in Postgres. Log error prominently.
                # Maybe schedule retry? For now, just log.

            # Return IDs or objects as needed
            return [p.product_id for p in new_db_products] # Example return

        except Exception as e:
            print(f"ERROR during DB commit stage: {e}")
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to save products to database: {e}")

    async def _process_image_with_ai(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sub-process to handle AI calls for a single image."""
        # print(f"Data : {task_data}")
        images = task_data["images_url"]
        # variant_id = task_data["variant_id"]
        product_index = task_data.get("product_index") # Pass product obj reference if needed

        embedding = None
        generated_description = None
        cropped_image_bytes= None

        try:
            # Download images in memory
            # try:
            #     image_bytes = [base64.b64encode(await utils.download_image(image, self.client)).decode() for image in images]
            # except Exception as e:
            #     print(f"Error while downloading images : {e}")
            #     raise Exception
            # 1. Object Detection (Get Cropped Image)
            # Assuming endpoint takes {'image': base64_encoded_image, 'name': '...'}
            # Process image_bytes (e.g., resize, base64 encode) based on endpoint needs
            # obj_det_payload = {"image": image_bytes, "title": task_data["norm_en_name"]} # Simplify payload
            detection_results = [utils._call_ai_service(settings.OBJECT_DETECTION_ENDPOINT, {"image": image, "title": task_data["norm_en_name"]}, self.client) for image in images]
            obj_det_result = await asyncio.gather(*detection_results)
            # print(f"Object : {obj_det_result}")
            cropped_image_bytes = [img.get("cropped_images", None) or images[index] for index, img in enumerate(obj_det_result)] # Assuming bytes returned

            if not cropped_image_bytes:
                print(f"WARN: No object detected for product {product_index}")
                # return {"variant_id": variant_id} # Return minimal info

            # # 2. Descriptive Model (Conditional)
            # if task_data["needs_desc_generation"]:
            #     desc_payload = {"image": cropped_image_bytes or image_bytes}
            #     desc_result = await utils._call_ai_service(settings.DESCRIPTIVE_MODEL_ENDPOINT, desc_payload, self.client)
            #     generated_description = desc_result.get("description")

            # 3. CLIP Model (Get Embedding)
            clip_payload = {
                "images": cropped_image_bytes ,
                "text": task_data["norm_en_name"],
                # "description": generated_description
            }
            clip_result = await utils._call_ai_service(settings.CLIP_ENDPOINT, clip_payload, self.client)
            # print(clip_result)
            embedding = clip_result.get("embeddings") # Assuming embedding vector returned

            return {
                "product_index": product_index,
                "embedding": embedding,
                # "generated_description": generated_description,
            }

        except Exception as e:
            print(f"ERROR in AI pipeline for product {product_index}, image index {task_data['product_index']}: {e}")
            # Return partial results or error indicator
            return {"product_index": product_index, "error": str(e)}


    async def update_product_variant(self, product_id: int, update_data: models.ProductUpdateInput, merchant_id_auth: int):
        # 1. Fetch Variant and Product, check ownership
        variant = self.get_product(product_id, merchant_id_auth)
        # print(f"Model : {update_data.model_dump()}")

        update_payload_dict = update_data.model_dump(exclude_unset=True)
        # print(f"Model : {update_payload_dict}")
        rerun_ai = "images" in update_payload_dict or "en_name" in update_payload_dict # Basic check
        image_name = utils.normalize_name(update_payload_dict["en_name"]) if "en_name" in  update_payload_dict else variant.en_name

        # 2. Normalize and Prepare Updates
        product_updates = {}
        # variant_updates = {}
        new_images_input = update_payload_dict.get("images") or variant.images
        payload = {}

        if "en_name" in update_payload_dict: product_updates["en_name"] = image_name
        if "ar_name" in update_payload_dict: product_updates["ar_name"] = utils.normalize_name(update_payload_dict["ar_name"])
        if "description" in update_payload_dict: product_updates["description"] = utils.normalize_description(update_payload_dict["description"])
        if "price" in update_payload_dict: 
            product_updates["price"] = update_payload_dict["price"]
            payload['price'] = update_payload_dict['price']
        else:
            payload["price"] = variant.price

        # Re-write
        if "color" in update_payload_dict:
            color_id = utils.map_color_from_db(update_payload_dict['color'], self.db)
            product_updates["color_id"] = color_id
            payload['color'] = update_payload_dict['color']
        else:
            payload["color"] = variant.color_obj.name if variant.color_obj else ""

        if "product_url" in update_payload_dict: product_updates["product_url"] = str(update_payload_dict["product_url"])
        if "disabled" in update_payload_dict: product_updates["disabled"] = update_payload_dict["disabled"]

        # 3. Handle Image Updates and AI Rerun (Simplified - Full AI run if images change)
        embeddings_to_update = {
            product_id: {
                "payload": payload
            }
        }


        if rerun_ai:
            # Similar logic as in add_products: download, process, call AI, get embeddings
            # This part needs careful implementation matching the add flow
            print(f"INFO: Rerunning AI pipeline for variant {product_id} named : {image_name} due to image/link change.")
            processed_image_urls, temp_image_urls = self.build_images_urls(new_images_input, image_name)
            ai_task_data = {
                "images_url": temp_image_urls,
                "norm_en_name": image_name,
                # "needs_desc_generation": False, # Flag if description needed
                "product_index" : 0
            }
            try:
                results = await self._process_image_with_ai(ai_task_data)
                embeddings_to_update[product_id]['embedding'] = results["embedding"][0]
                # print(embeddings_to_update[product_id]['embedding'])
            except Exception as e:
                print(f"Error while updating product {product_id} and getting new embeddings!")
            # ... [Placeholder for AI pipeline execution on new_images_input] ...
            # Example: Assume it populates embeddings_to_update[variant_id] = new_embedding

        # if change images, it will compare with current, in case of cloudflare it will delete image
        if new_images_input:
            images_to_remove = [utils._delete_from_s3(img) for img in variant.images if img not in new_images_input]
            # are_removed = await asyncio.gather(*images_to_remove)

            if not all(images_to_remove):
                print("Something went wrong while removing images!")

        # 4. Apply DB Updates
        try:
            if product_updates:
                self.db.query(database.Product).filter(database.Product.product_id == variant.product_id).update(product_updates)
            if embeddings_to_update[product_id]:
               
                if "embedding" not in embeddings_to_update[product_id]:
                    self.qdrant.set_payload(
                        collection_name=settings.QDRANT_COLLECTION,
                        payload=embeddings_to_update[product_id]["payload"],
                        points=[product_id],
                        wait=True
                    )
                    print(f"Payload-only update done for ID: {product_id}")

                # CASE 2: Vector update only
                elif not embeddings_to_update[product_id].get("payload"):
                    self.qdrant.update_vectors(
                        collection_name=settings.QDRANT_COLLECTION,
                        points={product_id: embeddings_to_update[product_id]["embedding"]},
                        wait=True
                    )
                    print(f"Vector-only update done for ID: {product_id}")

                # CASE 3: Full update (vector + payload)
                else:
                    point = qdrant_models.PointStruct(
                        id=product_id,
                        vector=embeddings_to_update[product_id]["embedding"],
                        payload=embeddings_to_update[product_id]["payload"]
                    )
                    self.qdrant.upsert(
                        collection_name=settings.QDRANT_COLLECTION,
                        points=[point],
                        wait=True
                    )
                    print(f"Full update done for ID: {product_id}")

            self.db.commit()
            self.db.refresh(variant)
            return variant # Or ProductOutput model
        # except Exception as e:
        #      print(f"ERROR updating variant {product_id}: {e}")
        #      self.db.rollback()
        #      raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update product variant.")
        finally:
            pass

    # --- Other Read/Delete/Disable Functions ---
    async def get_products_by_merchant(self, merchant_id: int, is_owner: bool , skip: int = 0, limit: int = 100):
        # Query products for a merchant with pagination, potentially eager loading variants
        # print(merchant_id)
        products = self.db.query(database.Product).filter(database.Product.merchant_id == merchant_id).order_by(database.Product.created_at)
        # products = self.db.query(database.Product).filter(database.Product.merchant_id == merchant_id).offset(skip).limit(limit)
        if not is_owner:
            products = products.filter(database.Product.disabled == False)
        # print(products.all())
        return products.offset(skip).limit(limit).all()

    async def get_variants_by_ids(self, products_ids: List[int], user_id: int):
        # Aliases for aggregation
        OverallProductUser = aliased(database.ProductUser)

        # Define likes and dislikes count expressions
        likes_count = func.sum(
            case(
                (OverallProductUser.action == database.ProductAction.like, 1),
                else_=0
            )
        ).label("likes_count")

        dislikes_count = func.sum(
            case(
                (OverallProductUser.action == database.ProductAction.dislike, 1),
                else_=0
            )
        ).label("dislikes_count")

        ranking_score_expr = (
            0.2 * func.coalesce(likes_count, 0) - 0.1 * func.coalesce(dislikes_count, 0)
        ).label("ranking_score")

        # Query products and their reaction aggregations
        products = self.db.query(
            database.Product,
            func.coalesce(likes_count, 0).label("total_likes"),
            func.coalesce(dislikes_count, 0).label("total_dislikes"),
            ranking_score_expr
        ).outerjoin(
            OverallProductUser, database.Product.product_id == OverallProductUser.product_id
        ).outerjoin(
            database.Color, database.Product.color_id == database.Color.color_id
        ).filter(
            database.Product.product_id.in_(products_ids),
            database.Product.disabled == False
        ).group_by(
            database.Product.product_id,
            database.Color.color_id  # Necessary if you're selecting color fields
        ).all()

        # Fetch user reactions if user_id provided
        reactions_data = {}
        if user_id:
            reactions = self.db.query(database.ProductUser).filter(
                database.ProductUser.product_id.in_(products_ids),
                database.ProductUser.user_id == user_id
            ).all()

            reactions_data = {
                react.product_id: react.action.value
                for react in reactions
            }

        # Process result rows
        processed_products_output: List[ProductOutput] = []
        for row in products:
            product_obj = row[0]
            total_likes = row[1]
            total_dislikes = row[2]
            ranking_score = row[3]
            user_reaction = reactions_data.get(product_obj.product_id)

            product_output = models.ProductOutput(
                product_id=product_obj.product_id,
                en_name=product_obj.en_name,
                ar_name=product_obj.ar_name,
                description=product_obj.description,
                price=product_obj.price,
                merchant_id=product_obj.merchant_id,
                color=product_obj.color.name if product_obj.color else None,
                images=product_obj.images,
                product_url=product_obj.product_url,
                disabled=product_obj.disabled,
                created_at=product_obj.created_at,
                updated_at=product_obj.updated_at,
                likes=total_likes,
                dislikes=total_dislikes,
                action=user_reaction,
                ranking_score=ranking_score
            )

            processed_products_output.append(product_output)

        return processed_products_output

    async def delete_product(self, product_id: int, merchant_id_auth: int):
        # Fetch product, check ownership, delete variants THEN product
        product = self.get_product(product_id, merchant_id_auth)

        # Delete images from s3 bucket first
        for image in product.images:
            utils._delete_from_s3(image)

        # Delete embeddings from Qdrant 
        try:
            operation_info = self.qdrant.delete(
                collection_name=settings.QDRANT_COLLECTION,
                points_selector=models.PointIdsList(points=[product.product_id]),
                wait=True,  # Wait for the operation to complete on the server (optional)
            )
            print(f"Successfully requested deletion of point with ID: {product_id}. Operation Info: {operation_info}")
        except Exception as e:
            print(f"Error deleting point with ID: {product_id}: {e}")

        # Delete product
        self.db.delete(product)
        self.db.commit()
        return {"detail": f"Product {product_id} deleted successfully."}

    async def disable_variant(self, product_id: int, merchant_id_auth: int, disable: bool = True):
        # Fetch variant, check ownership, update 'disabled' flag
        variant = self.get_product(product_id, merchant_id_auth)

        variant.disabled = disable
        self.db.commit()
        self.db.refresh(variant)
        return variant

    async def react_product(self, product_id: int, user_id: int, react: models.ProductReact):        
        product = self.get_product(product_id)
        react_record = self.db.query(database.ProductUser).filter(
            database.ProductUser.product_id== product_id,
            database.ProductUser.user_id == user_id
        ).first()

        desired_action = react.action.value

        try:
            if react_record:
                # A previous reaction exists
                if react_record.action.value == desired_action:
                    # User is trying to perform the same action again (e.g., liked, then liked again)
                    # This means "undo" the reaction
                    self.db.delete(react_record)
                    self.db.commit()
                    
                else:
                    # User is changing their reaction (e.g., liked, then disliked)
                    react_record.action = desired_action
                    self.db.add(react_record)
                    
                    self.db.commit()
                    self.db.refresh(react_record)
            else:
                # No previous reaction exists, create a new one
                new_reaction = database.ProductUser(
                    product_id=product.product_id,
                    user_id=user_id,
                    action=desired_action
                )
                self.db.add(new_reaction)
                self.db.commit()
                self.db.refresh(new_reaction)
                
            return True
        
        except Exception as e:
            print(f"Error while saving database : {str(e)}")
            self.db.rollback()
            raise e

