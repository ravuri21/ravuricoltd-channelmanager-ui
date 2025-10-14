import csv, sys
from models import SessionLocal, Unit, init_db

def import_csv(path):
    init_db()
    db = SessionLocal()
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.add(Unit(
                ota=row['OTA Name'],
                property_id=row['Property ID / Room ID'],
                ical_url=row['iCal URL']
            ))
    db.commit()
    db.close()
    print("Imported properties from", path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backend/import_properties.py backend/ota_properties_prefilled.csv")
    else:
        import_csv(sys.argv[1])
