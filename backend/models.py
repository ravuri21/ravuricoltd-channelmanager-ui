# backend/models.py
import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func, ForeignKey, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Use persistent DB path from env (Render persistent disk is /var/data)
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///channel_manager.db")

# Create engine (SQLite needs special connect args)
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Unit(Base):
    __tablename__ = "units"
    id = Column(Integer, primary_key=True, index=True)
    ota = Column(String(50), index=True)
    property_id = Column(String(200), index=True)
    ical_url = Column(Text)
    last_sync = Column(DateTime, server_default=func.now(), onupdate=func.now())
    blocks = relationship("AvailabilityBlock", back_populates="unit", cascade="all, delete-orphan")
    rates = relationship("RatePlan", back_populates="unit", cascade="all, delete-orphan")

class AvailabilityBlock(Base):
    __tablename__ = "availability_blocks"
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id"))
    start_date = Column(String(20))  # YYYY-MM-DD
    end_date = Column(String(20))    # YYYY-MM-DD (checkout, exclusive)
    source = Column(String(50), default="manual")  # manual, direct, ical, booking, airbnb, agoda...
    note = Column(Text, default="")
    unit = relationship("Unit", back_populates="blocks")

class RatePlan(Base):
    __tablename__ = "rate_plans"
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id"))
    base_rate = Column(Float, default=1500.0)  # THB
    currency = Column(String(8), default="THB")
    unit = relationship("Unit", back_populates="rates")

def init_db():
    Base.metadata.create_all(bind=engine)
