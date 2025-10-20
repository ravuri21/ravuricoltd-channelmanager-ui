/* style-luxury.css — "Luxury" theme to match the mock */
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700;800&display=swap');

:root{
  --brand-red:#e11d48;
  --brand-dark:#0f1724;
  --muted:#6b7280;
  --accent:#0ea5a4;
  --bg:#fbfaf9;
  --card:#ffffff;
  --primary:#2563eb;
  --card-radius:14px;
  --max-w:1100px;
}

/* Global baseline */
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;
  font-family:'Poppins',system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);
  color:var(--brand-dark);
  -webkit-font-smoothing:antialiased;
}

/* Hero / header big visual (mock) */
.site-hero{
  background:linear-gradient(180deg,#ffffff 0%, #fff8f6 40%, #f9f6f5 100%);
  border-bottom:1px solid rgba(2,6,23,0.04);
  padding:28px 0;
}
.hero-inner{
  max-width:var(--max-w);
  margin:0 auto;
  padding:0 16px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
}
.brand{
  display:flex;
  align-items:center;
  font-weight:800;
  font-size:1.55rem;
  letter-spacing:-0.5px;
}
.brand-red{ color:var(--brand-red); margin-right:6px; }
.brand-dark{ color:var(--brand-dark); }

/* small language + badge stack */
.lang-row{ display:flex; gap:12px; align-items:center; color:var(--muted); font-weight:600; }
.stripe-badge{
  display:inline-block;
  border-radius:8px;
  padding:6px 8px;
  background:#fff;
  border:1px solid #eef3ff;
  color:#0b5cff;
  font-size:0.86rem;
}

/* page container */
.wrap{ max-width:var(--max-w); margin:18px auto; padding:20px; box-sizing:border-box; }

/* trust / guarantees row (cards) */
.trust-row{ display:flex; gap:12px; margin:14px 0 20px; flex-wrap:wrap; align-items:stretch; }
.trust-card{
  flex:1;
  min-width:180px;
  background:var(--card);
  border-radius:10px;
  padding:12px 14px;
  border:1px solid #f1f5f9;
  box-shadow:0 10px 28px rgba(2,6,23,0.04);
}
.trust-title{ font-weight:700; margin-bottom:6px; color:var(--brand-dark) }

/* grid & cards */
.grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:20px; margin-top:6px }
.card{
  background:var(--card);
  border-radius:var(--card-radius);
  overflow:hidden;
  display:flex;
  flex-direction:column;
  box-shadow:0 12px 36px rgba(4,10,25,0.06);
  transition:transform .18s ease, box-shadow .18s ease;
}
.card:hover{ transform:translateY(-10px); box-shadow:0 26px 54px rgba(4,10,25,0.12) }
.card img{ width:100%; height:220px; object-fit:cover; display:block; }
.pad{ padding:16px; display:flex; flex-direction:column; gap:10px; flex:1; justify-content:space-between; }
.title{ font-weight:800; font-size:1.08rem; color:var(--brand-dark); }
.meta{ color:var(--muted); font-size:0.95rem }
.price{ font-weight:800; font-size:1.05rem; color:var(--brand-red) }
.teaser{ color:#374151; margin-top:6px }

/* card actions */
.card-actions{ display:flex; gap:10px; margin-top:4px }
.btn{ padding:10px 12px; border-radius:10px; font-weight:700; cursor:pointer; text-align:center; display:inline-block; text-decoration:none; flex:1 }
.btn-outline{ background:transparent; border:1px solid var(--accent); color:var(--accent) }
.btn-outline:hover{ background:var(--accent); color:#fff }
.btn-primary{ background:var(--brand-red); color:#fff; box-shadow:0 8px 26px rgba(225,29,72,0.18) }
.btn-primary:hover{ background:#c40d40 }

/* footer */
.page-footer{ text-align:center; margin-top:24px; color:var(--muted); font-size:.9rem; padding-bottom:24px }

/* responsive tweaks */
@media (max-width:900px){
  .card img{ height:170px }
}
@media (max-width:520px){
  .brand{ font-size:1.2rem }
  .card img{ height:140px }
  .grid{ gap:14px }
}
