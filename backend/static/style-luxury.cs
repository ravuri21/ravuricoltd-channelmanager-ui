/* Theme B — Luxury Look */
:root {
  --brand-red:#e11d48;
  --brand-dark:#111827;
  --muted:#6b7280;
  --gold:#d4af37;
  --bg:#faf9f7;
  --card:#ffffff;
  --accent:#0ea5a4;
}

/* general */
body {
  margin:0;
  font-family:"Poppins",system-ui,sans-serif;
  background:var(--bg);
  color:var(--brand-dark);
}
a{text-decoration:none;color:inherit}
img{display:block;width:100%;border:0}

/* hero */
.hero {
  background:linear-gradient(135deg,#fff 0%,#fef7f4 100%);
  border-bottom:1px solid #eee;
  padding:22px 0;
}
.hero-inner {
  max-width:1100px;
  margin:auto;
  display:flex;
  justify-content:space-between;
  align-items:center;
  padding:0 14px;
}
.brand {
  font-size:1.6rem;
  font-weight:900;
  letter-spacing:-0.5px;
}
.brand-red{color:var(--brand-red)}
.brand-dark{color:var(--brand-dark);margin-left:6px}
.lang{color:var(--muted);font-weight:600}
.stripe-badge{background:#fff;padding:6px 8px;border-radius:8px;border:1px solid #eee;margin-left:10px;font-size:.85rem;color:#0b5cff}

/* trust */
.trust{display:flex;gap:14px;flex-wrap:wrap;max-width:1100px;margin:24px auto;padding:0 14px}
.trust-card{flex:1;min-width:240px;background:var(--card);border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,0.04);padding:14px 16px}
.trust-card h3{margin:0 0 6px;font-size:1rem;color:var(--brand-dark)}

/* villas grid */
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;max-width:1100px;margin:0 auto 40px;padding:0 14px}
.villa{background:var(--card);border-radius:14px;overflow:hidden;box-shadow:0 10px 28px rgba(0,0,0,0.06);transition:transform .2s,box-shadow .2s}
.villa:hover{transform:translateY(-8px);box-shadow:0 16px 40px rgba(0,0,0,0.12)}
.info{padding:16px}
.info h2{margin:0 0 6px;font-size:1.2rem;font-weight:700;color:var(--brand-dark)}
.price{font-weight:800;margin-bottom:8px;color:var(--brand-red)}
.teaser{color:#444;font-size:.95rem;margin-bottom:12px}
.actions{display:flex;gap:10px}
.btn{flex:1;text-align:center;padding:10px 12px;border-radius:10px;font-weight:700;transition:background .2s,color .2s}
.view{border:1px solid var(--accent);color:var(--accent);background:transparent}
.view:hover{background:var(--accent);color:#fff}
.book{background:var(--brand-red);color:#fff;box-shadow:0 4px 10px rgba(225,29,72,.3)}
.book:hover{background:#c40d40}

/* footer */
.footer{text-align:center;color:var(--muted);font-size:.9rem;margin-bottom:20px}
