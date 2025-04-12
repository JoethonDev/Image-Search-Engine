from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, text, ARRAY, UUID, Boolean, TIMESTAMP, Date, func
from sqlalchemy.orm import declarative_base, Session, relationship
from sqlalchemy.dialects.postgresql import BYTEA
from geoalchemy2.types import Geometry
import uuid

# Replace with your actual database URL
DATABASE_URL = "postgresql://avnadmin:AVNS_pJ81YzNkQZ50I53daVx@image-search-image-search-engine.h.aivencloud.com:28638/image-search"
engine = create_engine(DATABASE_URL)

Base = declarative_base()

class Account(Base):
    __tablename__ = "accounts"
    account_id = Column(Integer, primary_key=True, autoincrement="auto")
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now(), server_default=func.now())

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.account_id"))
    name = Column(String(255))
    phone_number = Column(String(20))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now(), server_default=func.now())
    address = Column(String)
    date_of_birth = Column(Date)
    account = relationship("Account")

class UserHistory(Base):
    __tablename__ = "user_history"
    record_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    image = Column(BYTEA)
    text = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class Merchant(Base):
    __tablename__ = "merchants"
    merchant_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.account_id"))
    store_name = Column(String(255), unique=True, nullable=False)
    website = Column(String(255))
    contact_link = Column(ARRAY(String))
    offline_location = Column(Geometry(geometry_type='POINT', srid=4326))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now(), server_default=func.now())

class Product(Base):
    __tablename__ = "products"
    product_id = Column(Integer, primary_key=True)
    en_name = Column(String(255), nullable=False)
    ar_name = Column(String(255), nullable=False)
    description = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    merchant_id = Column(Integer, ForeignKey("merchants.merchant_id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now(), server_default=func.now())

class Color(Base):
    __tablename__ = "colors"
    color_id = Column(Integer, primary_key=True)
    color = Column(String(255), unique=True, nullable=False)

class ProductVariant(Base):
    __tablename__ = "product_variants"
    product_id = Column(Integer, ForeignKey("products.product_id"), nullable=False)
    variant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    color_id = Column(Integer, ForeignKey("colors.color_id"), nullable=False)
    images = Column(ARRAY(String), nullable=False)
    product_url = Column(String(255), nullable=False)
    disabled = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now(), server_default=func.now())

class UserWishlist(Base):
    __tablename__ = "user_wishlist"
    user_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.variant_id"), primary_key=True)
    added_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

# Create tables if they don't exist
def create_tables():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.commit()
    Base.metadata.create_all(engine)
    # engine.dispose()
    print("Database tables created (if needed).")