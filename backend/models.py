# backend/models.py
import os
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Float,
    ForeignKey, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# -------------------------------------------------------------------
# DATABASE URL
# - For Neon (Postgres) use: postgresql+psycopg://... ?sslmode=require
# - Falls back to local SQLite if env var is missing (for dev)
# -------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///channel_manager.db").strip()

is_sqlite = DATABASE_URL.startswith("sqlite")

# Engine options:
# - pool_pre_ping: avoid stale connections
# - For SQLite: allow single-threaded check_same_thread=False
engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if is_sqlite else {},
)

# Session factory
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # keep objects usable after commit
)

Base = declarative_base()

# -------------------------------------------------------------------
# MODELS
# -------------------------------------------------------------------
class Unit(Base):
    __tablename__ = "units"

    id = Column(Integer, primary_key=True, index=True)
    ota = Column(String(50), index=True)                # Airbnb / Booking.com / Agoda
    property_id = Column(String(200), index=True)       # OTA property/room identifier
    ical_url = Column(Text)                             # OTA iCal feed URL
    last_sync = Column(DateTime, server_default=func.now(), onupdate=func.now())

    blocks = relationship(
        "AvailabilityBlock",
        back_populates="unit",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    rates = relationship(
        "RatePlan",
        back_populates="unit",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

class AvailabilityBlock(Base):
    __tablename__ = "availability_blocks"

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="CASCADE"), index=True)

    # Store as YYYY-MM-DD (end = checkout/exclusive)
    start_date = Column(String(20), nullable=False)
    end_date   = Column(String(20), nullable=False)

    # manual / direct / airbnb / booking.com / agoda / ical, etc.
    source = Column(String(50), default="manual", index=True)
    note   = Column(Text, default="")

    unit = relationship("Unit", back_populates="blocks")

class RatePlan(Base):
    __tablename__ = "rate_plans"

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="CASCADE"), index=True)

    base_rate = Column(Float, default=1500.0)  # nightly price fallback
    weekend_rate = Column(Float, nullable=True)  # optional Fri/Sat special price (can be NULL)
    currency  = Column(String(8), default="THB")

    unit = relationship("Unit", back_populates="rates")

# -------------------------------------------------------------------
# INIT
# -------------------------------------------------------------------
def init_db() -> None:
    """
    Create tables if they don't exist.
    Call this once at app startup.
    NOTE: for adding new columns to existing tables in production (Postgres)
    you should run an ALTER TABLE migration. init_db() will create missing tables
    but won't add columns to an existing Postgres table.
    """
    Base.metadata.create_all(bind=engine)
