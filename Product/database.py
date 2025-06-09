from qdrant_client import QdrantClient, models
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, text, ARRAY, Boolean, TIMESTAMP, func
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.hybrid import hybrid_property
from config import settings
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM # For PostgreSQL specific ENUM
import enum



# Replace with your actual database URL
DATABASE_URL = "postgresql://avnadmin:AVNS_pJ81YzNkQZ50I53daVx@image-search-image-search-engine.h.aivencloud.com:28638/image-search"
engine = create_engine(DATABASE_URL)
Base = declarative_base()

class Product(Base):
    __tablename__ = "products"
    product_id = Column(Integer, primary_key=True, autoincrement="auto")
    en_name = Column(String(255), nullable=False)
    ar_name = Column(String(255), nullable=False)
    description = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    color_id = Column(Integer, ForeignKey("colors.color_id"), nullable=True)
    images = Column(ARRAY(String), nullable=False)
    product_url = Column(String(255), nullable=True)
    disabled = Column(Boolean, default=False)
    merchant_id = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now(), server_default=func.now())

    # Define relationship to Color
    color_obj = relationship("Color", back_populates="products")

    # If your ProductOutput expects 'color' as a string, you might need this
    # if you want to access it directly from a Product instance after a join.
    @hybrid_property
    def color(self):
        return self.color_obj.name if self.color_obj else None

class Color(Base):
    __tablename__ = "colors"
    color_id = Column(Integer, primary_key=True, autoincrement="auto")
    color = Column(String(255), unique=True, nullable=False)
    parent_color_id = Column(Integer, ForeignKey("colors.color_id"), nullable=True)

    # Self-referential relationship
    parent_color = relationship("Color", remote_side=[color_id], backref="shades")
    products = relationship("Product", back_populates="color_obj")


# 1. Define the Enum for actions
class ProductAction(enum.Enum):
    like = "like"
    dislike = "dislike"


# 3. Define the ProductUser model (table)
class ProductUser(Base):
    __tablename__ = "product_user"

    # Composite Primary Key: product_id and user_id together are unique
    product_id = Column(Integer, ForeignKey("products.product_id"), primary_key=True)
    user_id = Column(Integer, primary_key=True)
    # action = Column(PG_ENUM(ProductAction, name="product_action_enum", create_type=False), nullable=False)
    action = Column(PG_ENUM(ProductAction, name="product_action_enum", create_type=True), nullable=False)



    def __repr__(self):
        return f"<ProductUser(product_id={self.product_id}, user_id={self.user_id}, action='{self.action.value}')>"


# Create Tables
def create_postgres_tables():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.commit()
    Base.metadata.create_all(engine)
    print("Database tables created (if needed).")

# Qdrant Setup
# --- Qdrant Connection Details ---
def create_qdrant_collection():
    # 1. Qdrant Cloud (Uncomment and configure if using Cloud)
    client = QdrantClient(
        url=settings.QDRANT_ENDPOINT,
        api_key=settings.QDRANT_KEY,
    )

    # --- Collection Definition ---
    COLLECTION_NAME = settings.QDRANT_COLLECTION
    VECTOR_SIZE = 512  # The dimensionality of your embeddings

    # Define the vector parameters for your collection
    vector_params = models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE)

    # --- Create the Collection (if it doesn't exist) ---
    try:
        client.get_collection(collection_name=COLLECTION_NAME)
        print(f"Collection '{COLLECTION_NAME}' already exists.")
    except Exception as e:
        print("Collection" in str(e))
        if "Collection" in str(e) and "Not found" in str(e):
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=vector_params,
            )
            print(f"Collection '{COLLECTION_NAME}' created successfully.")
        else:
            print(f"Error checking/creating collection: {e}")

    print("Initial Qdrant setup complete.")