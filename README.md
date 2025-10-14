# Ravuricoltd Channel Manager — Ready-to-Host (with React Dashboard)

This package is production-ready for **Render.com** (free) and includes:
- 30 OTA listings via **iCal** sync (Airbnb / Booking.com / Agoda)
- **Stripe test mode** for direct bookings
- **English + Thai** language toggle
- React dashboard to manage:
  - Units list
  - **Block / Unblock** dates (saved to DB; used to prevent double-booking and for future push)
- Backend serves the built frontend at **/app**

## Deploy on Render (10–15 minutes)

1) Create a GitHub repo and upload these files.

2) In Render → **New → Web Service → Connect your repo**. Use:
- **Environment:** Python
- **Build Command:**
```
pip install -r requirements.txt
python backend/import_properties.py backend/ota_properties_prefilled.csv
npm ci --prefix frontend
npm run build --prefix frontend
mkdir -p backend/static/app && cp -r frontend/dist/* backend/static/app/
```
- **Start Command:**
```
gunicorn -w 4 -b 0.0.0.0:$PORT backend.server:app
```
- **Environment Variables:**
  - `ADMIN_EMAIL` = `pradeep@ravuricoltd.com`
  - `ADMIN_PASSWORD` = `ChangeMe123!`  (change after first login)
  - `STRIPE_SECRET_KEY` = `sk_test_4eC39HqLyjWDarjtT1zdp7dc`
  - `APP_LANG_DEFAULT` = `en`
  - `TZ` = `Asia/Bangkok`

3) Open your Render URL.  
- Dashboard (React): `/app`  
- Classic view (server templates): `/`

Add to iPhone: Safari → Share → **Add to Home Screen**.

## Local run (optional)

```
# backend
pip install -r requirements.txt
python backend/import_properties.py backend/ota_properties_prefilled.csv

# frontend
npm ci --prefix frontend
npm run build --prefix frontend
mkdir -p backend/static/app && cp -r frontend/dist/* backend/static/app/

# run server
export ADMIN_EMAIL=pradeep@ravuricoltd.com
export ADMIN_PASSWORD=ChangeMe123!
export STRIPE_SECRET_KEY=sk_test_4eC39HqLyjWDarjtT1zdp7dc
gunicorn -w 4 -b 0.0.0.0:5000 backend.server:app
# open http://localhost:5000/app
```

## Notes
- **Blocks** are stored server-side and shown in the React UI. iCal fetch continues in background to ingest OTA bookings.
- Later we can add iCal **export** for your blocks or API pushes once OTAs grant API access.
