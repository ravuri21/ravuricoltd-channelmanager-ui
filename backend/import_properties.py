import csv, sys
from models import SessionLocal, Unit, init_db
from sqlalchemy import and_

def import_csv(path):
    init_db()
    db = SessionLocal()
    added = 0
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ota = row['OTA Name'].strip()
            pid = row['Property ID / Room ID'].strip()
            ical = row['iCal URL'].strip()
            # Skip if already exists (avoid duplicates on restarts)
            exists = db.query(Unit).filter(and_(Unit.ota==ota, Unit.property_id==pid)).first()
            if not exists:
                db.add(Unit(ota=ota, property_id=pid, ical_url=ical))
                added += 1
    db.commit()
    db.close()
    print(f"Imported properties from {path}. New rows added: {added}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backend/import_properties.py backend/ota_properties_prefilled.csv")
    else:
        import_csv(sys.argv[1])
