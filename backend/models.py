from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///channel_manager.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Unit(Base):
    __tablename__ = "units"
    id = Column(Integer, primary_key=True, index=True)
    ota = Column(String(50), index=True)
    property_id = Column(String(200), index=True)
    ical_url = Column(Text)
    last_sync = Column(DateTime, server_default=func.now(), onupdate=func.now())

def init_db():
    Base.metadata.create_all(bind=engine)
