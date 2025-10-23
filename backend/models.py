# backend/models.py
import os
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Float,
    ForeignKey, func, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

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
    date_rates = relationship(
        "DateRate",
        back_populates="unit",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def get_active_rateplan(self, session: Optional[Session] = None) -> Optional["RatePlan"]:
        """
        Convenience: return the first RatePlan associated with this unit.
        If there's none, returns None.
        If called on a detached Unit (no lazy-loaded rates), you can provide a session to query.
        """
        if self.rates:
            return self.rates[0]
        if session is not None:
            return session.query(RatePlan).filter_by(unit_id=self.id).order_by(RatePlan.id).first()
        return None


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

    base_rate = Column(Float, default=1500.0)  # nightly price
    weekend_rate = Column(Float, nullable=True)  # special Fri/Sat rate (if None, use base_rate)
    currency  = Column(String(8), default="THB")

    unit = relationship("Unit", back_populates="rates")

    # --------------------
    # Pricing helpers
    # --------------------
    @staticmethod
    def _parse_date_str(d: str) -> date:
        """
        Parse YYYY-MM-DD into date object. Expect valid format.
        """
        return datetime.strptime(d, "%Y-%m-%d").date()

    @staticmethod
    def _daterange(start: date, end: date):
        """
        Yield dates from start (inclusive) to end (exclusive).
        """
        cur = start
        while cur < end:
            yield cur
            cur += timedelta(days=1)

    def get_nightly_rates(self, start: str, end: str, session: Optional[Session] = None) -> List[Dict]:
        """
        Return a list of nightly rate dicts for nights from `start` (check-in) to `end` (checkout exclusive).
        Each dict: {
            "date": "YYYY-MM-DD",
            "price": float,
            "is_override": bool,
            "is_weekend": bool
        }

        - If a DateRate override exists for a date, its price is used.
        - Else, if the date is Friday or Saturday and weekend_rate is set (not None), use weekend_rate.
        - Else use base_rate.

        session: optional SQLAlchemy session if the RatePlan instance doesn't have `unit` or its relationships loaded.
        """
        start_date = self._parse_date_str(start)
        end_date = self._parse_date_str(end)

        # Collect overrides for the unit between start and end
        overrides = {}
        if self.unit and self.unit.date_rates:
            for dr in self.unit.date_rates:
                # only store relevant ones; date stored as 'YYYY-MM-DD' in DateRate.date
                if start <= dr.date < end:
                    overrides[dr.date] = dr.price
        else:
            # Try to load from DB if session is provided
            if session is not None:
                q = session.query(DateRate).filter(
                    DateRate.unit_id == self.unit_id,
                    DateRate.date >= start,
                    DateRate.date < end
                )
                for dr in q:
                    overrides[dr.date] = dr.price

        breakdown = []
        for d in self._daterange(start_date, end_date):
            dstr = d.isoformat()
            weekday = d.weekday()  # Monday=0 ... Sunday=6
            is_weekend = weekday in (4, 5)  # Friday (4) or Saturday (5)
            is_override = dstr in overrides
            if is_override:
                price = float(overrides[dstr])
            else:
                if is_weekend and (self.weekend_rate is not None):
                    price = float(self.weekend_rate)
                else:
                    price = float(self.base_rate)
            breakdown.append({
                "date": dstr,
                "price": price,
                "is_override": is_override,
                "is_weekend": is_weekend,
            })
        return breakdown

    def calculate_total(self, start: str, end: str, session: Optional[Session] = None) -> Dict:
        """
        Returns:
        {
            "total": <float>,
            "currency": "<currency>",
            "nights": <int>,
            "breakdown": [ {date, price, is_override, is_weekend}, ... ]
        }
        """
        breakdown = self.get_nightly_rates(start, end, session=session)
        total = sum(item["price"] for item in breakdown)
        return {
            "total": float(total),
            "currency": self.currency,
            "nights": len(breakdown),
            "breakdown": breakdown,
        }


class DateRate(Base):
    """
    Per-date override price for a unit.

    Each row represents an override price for a specific date (YYYY-MM-DD).
    """
    __tablename__ = "date_rates"
    __table_args__ = (UniqueConstraint("unit_id", "date", name="uix_unit_date"),)

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="CASCADE"), index=True)
    # store date as YYYY-MM-DD (string) for simplicity / portability with your current codebase
    date = Column(String(20), nullable=False, index=True)
    price = Column(Float, nullable=False)

    unit = relationship("Unit", back_populates="date_rates")


# -------------------------------------------------------------------
# INIT
# -------------------------------------------------------------------
def init_db() -> None:
    """
    Create tables if they don't exist.
    Call this once at app startup.
    """
    Base.metadata.create_all(bind=engine)
