"""
Categories tab data model. CategoryGroup covers the top-level grouping
seen in Copilot's Categories tab (Essential, Neutral, Transportation,
etc.) -- Category rows nest under a group.
"""
import uuid
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class CategoryGroup(Base):
    __tablename__ = "category_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)  # "Essential", "Neutral", "Transportation"
    sort_order = Column(Numeric, nullable=False, default=0)

    categories = relationship("Category", back_populates="group")


class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    color = Column(String, nullable=False)  # hex string, e.g. "#4CAF50"
    icon = Column(String, nullable=False)  # emoji or icon identifier
    budget = Column(Numeric(12, 2), nullable=True)  # optional, per spec

    group_id = Column(UUID(as_uuid=True), ForeignKey("category_groups.id"), nullable=True)
    group = relationship("CategoryGroup", back_populates="categories")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
