# backend/models.py
import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func, ForeignKey, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Prefer env var; fall back to a safe temp path on Render Free
DEFAULT_SQLITE = "sqlite:////tmp/channel_manager.db"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE)

# If using sqlite with an absolute filesystem path, make sure the directory exists
def _ensure_sqlite_dir(url: str):
    # Formats we expect:
    #  - sqlite:////absolute/path.db
    #  - sqlite:///relative.db
    #  - sqlite:// (memory)  -> ignore
    if not url.startswith("sqlite"):
        return
    # absolute path form
    prefix = "sqlite:////"
    if url.startswith(prefix):
        path = url[len(prefix):]
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass

_ensure_sqlite_dir(DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
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
    source = Column(String(50), default="manual")  # manual, direct, hold, ota name
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
