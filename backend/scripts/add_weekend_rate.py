# scripts/add_weekend_rate.py
from sqlalchemy import text
from backend.models import engine  # ✅ import from your backend package
import os

print("Using DATABASE_URL:", os.getenv("DATABASE_URL", "(not set)"))

def column_exists(conn):
    q = text("""
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'rate_plans' AND column_name = 'weekend_rate'
      LIMIT 1
    """)
    r = conn.execute(q).fetchone()
    return bool(r)

with engine.connect() as conn:
    if column_exists(conn):
        print("✅ Column 'weekend_rate' already exists. Nothing to do.")
    else:
        print("🛠 Adding column 'weekend_rate' to rate_plans...")
        conn.execute(text("ALTER TABLE rate_plans ADD COLUMN weekend_rate double precision"))
        conn.commit()
        print("✅ Done! Column 'weekend_rate' added successfully.")
