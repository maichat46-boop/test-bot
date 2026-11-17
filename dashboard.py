"""لوحة تحكم الأدمن (مستخدم واحد)."""
import os, hmac, time, secrets, threading, requests
from datetime import date, timedelta
from markupsafe import Markup
from flask import Flask, request, session, redirect, url_for, render_template, flash, abort
from jinja2 import DictLoader
import db, ops
from ichancy import Ichancy

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
api = Ichancy()
USER, PASS = os.getenv("ADMIN_USER", "admin"), os.getenv("ADMIN_PASSWORD", "")
TOKEN = os.getenv("BOT_TOKEN", "")
_fails, _cache = {}, {"t": 0, "v": None}

def tg_send(chat, text):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat, "text": text}, timeout=15)
        return r.ok
    except Exception: return False

ICONS = {
 "home": '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
 "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
 "swap": '<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/>',
 "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
 "mail": '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
 "gift": '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13"/><path d="M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/><path d="M7.5 8a2.5 2.5 0 0 1 0-5A4.8 8 0 0 1 12 8a4.8 8 0 0 1 4.5-5 2.5 2.5 0 0 1 0 5"/>',
 "mega": '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
 "sliders": '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
 "out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
}
def ico(n):
    return Markup('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>' % ICONS[n])
ST_AR = {"pending": "قيد المراجعة", "approved": "مقبول", "rejected": "مرفوض", "done": "مكتمل", "failed": "فشل"}

@app.context_processor
def ctx():
    session.setdefault("_t", secrets.token_hex(16))
    c = {"tok": session["_t"], "kind_ar": db.KIND_AR, "st_ar": ST_AR, "ico": ico, "ep": request.endpoint}
    if session.get("ok"):
        c["nav"] = [("home", "/", "نظرة عامة", "home", 0), ("requests_", "/requests", "الطلبات", "inbox",
                    db.q("SELECT count(*) FROM requests WHERE status='pending'", one=True)[0]),
                    ("users", "/users", "المستخدمون", "users", 0), ("transactions", "/transactions", "المعاملات", "swap", 0),
                    ("messages", "/messages", "الرسائل", "mail", db.q("SELECT count(*) FROM messages WHERE reply IS NULL", one=True)[0]),
                    ("gifts", "/gifts", "الهدايا", "gift", 0), ("broadcast", "/broadcast", "بث جماعي", "mega", 0),
                    ("settings", "/settings", "الإعدادات", "sliders", 0)]
    return c

@app.before_request
def guard():
    if request.method == "POST" and not hmac.compare_digest(request.form.get("_t", ""), session.get("_t", "x")):
        abort(400)
    if request.endpoint not in ("login", "static", "healthz") and not session.get("ok"):
        return redirect(url_for("login"))

@app.route("/healthz")
def healthz():
    return "ok"  # لفحوص الاستضافة وخدمات إبقاء الخدمة مستيقظة

@app.route("/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr
    if request.method == "POST":
        n, until = _fails.get(ip, (0, 0))
        if time.time() < until:
            flash("محاولات كثيرة، انتظر 5 دقائق."); return render_template("login.html")
        ok = PASS and hmac.compare_digest(request.form["u"], USER) and hmac.compare_digest(request.form["p"], PASS)
        if ok:
            session.clear(); session["ok"] = True; _fails.pop(ip, None); return redirect("/")
        n += 1; _fails[ip] = (n, time.time() + 300 if n >= 5 else 0)
        flash("بيانات الدخول غير صحيحة.")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/")
def home():
    one = lambda s: db.q(s, one=True)[0]
    s = dict(
        users=one("SELECT count(*) FROM users"), accounts=one("SELECT count(*) FROM users WHERE game_login IS NOT NULL"),
        today=one("SELECT count(*) FROM users WHERE date(created_at)=date('now','localtime')"),
        wallets=one("SELECT coalesce(sum(wallet),0) FROM users"),
        dep=one("SELECT coalesce(sum(nsp),0) FROM tx WHERE kind='deposit_game' AND date(created_at)=date('now','localtime')"),
        wd=one("SELECT coalesce(-sum(nsp),0) FROM tx WHERE kind='withdraw_game' AND date(created_at)=date('now','localtime')"),
        unread=one("SELECT count(*) FROM messages WHERE reply IS NULL"), pend=one("SELECT count(*) FROM requests WHERE status='pending'"),
        failed=one("SELECT count(*) FROM tx WHERE status='failed'"))
    if time.time() - _cache["t"] > 60:
        _cache.update(t=time.time(), v=api.agent_balance())
    recent = db.q("SELECT t.*, u.game_login FROM tx t LEFT JOIN users u USING(tg_id) ORDER BY t.id DESC LIMIT 8")
    pending = db.q("SELECT r.*, u.game_login FROM requests r LEFT JOIN users u USING(tg_id) WHERE r.status='pending' ORDER BY r.id LIMIT 8")
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    agg = {(r[0], r[1]): r[2] for r in db.q("SELECT date(created_at), kind, sum(abs(nsp)) FROM tx WHERE kind IN ('deposit_game','withdraw_game') AND date(created_at)>=? GROUP BY 1,2", (days[0],))}
    series = [{"d": d[5:], "dep": agg.get((d, "deposit_game"), 0), "wd": agg.get((d, "withdraw_game"), 0)} for d in days]
    mx = max([1] + [x["dep"] for x in series] + [x["wd"] for x in series])
    for x in series: x["hd"], x["hw"] = round(x["dep"] * 100 / mx), round(x["wd"] * 100 / mx)
    return render_template("home.html", rate=db.getf("exchange_rate"), s=s, agent=_cache["v"], mock=api.mock,
                           recent=recent, pending=pending, series=series, methods=METHODS_AR)

@app.route("/users")
def users():
    term = request.args.get("q", "").strip()
    like = f"%{term}%"
    rows = db.q("SELECT * FROM users WHERE ?='' OR CAST(tg_id AS TEXT) LIKE ? OR tg_username LIKE ? OR game_login LIKE ? ORDER BY created_at DESC LIMIT 200",
                (term, like, like, like))
    return render_template("users.html", rows=rows, term=term)

@app.route("/user/<int:tg>", methods=["GET", "POST"])
def user(tg):
    u = db.get_user(tg) or abort(404)
    if request.method == "POST":
        act = request.form["act"]
        if act == "ban":
            db.x("UPDATE users SET banned=1-banned WHERE tg_id=?", (tg,)); flash("تم تحديث حالة الحظر.")
        elif act == "adjust":
            try: amt = round(float(request.form["amount"]), 2)
            except ValueError: amt = 0
            ok = amt != 0 and (db.wallet_add(tg, amt) if amt > 0 else db.wallet_take(tg, -amt))
            if ok: db.log(tg, "admin_adjust", amt, note=request.form.get("note", "")[:200]); flash("تم تعديل الرصيد.")
            else: flash("المبلغ غير صالح أو الرصيد لا يكفي.")
        return redirect(url_for("user", tg=tg))
    txs = db.q("SELECT * FROM tx WHERE tg_id=? ORDER BY id DESC LIMIT 50", (tg,))
    n = db.q("SELECT count(*) FROM users WHERE referrer=?", (tg,), one=True)[0]
    return render_template("user.html", u=db.get_user(tg), txs=txs, refs=n)

@app.route("/transactions")
def transactions():
    kind = request.args.get("kind", "")
    rows = db.q("SELECT t.*, u.game_login FROM tx t LEFT JOIN users u USING(tg_id) WHERE ?='' OR t.kind=? ORDER BY t.id DESC LIMIT 300", (kind, kind))
    return render_template("tx.html", rows=rows, kind=kind)

@app.route("/messages", methods=["GET", "POST"])
def messages():
    if request.method == "POST":
        m = db.q("SELECT * FROM messages WHERE id=?", (request.form["id"],), one=True) or abort(404)
        text = request.form["reply"].strip()
        if text and tg_send(m["tg_id"], f"💬 رد الإدارة:\n\n{text}"):
            db.x("UPDATE messages SET reply=?, replied_at=datetime('now','localtime') WHERE id=?", (text, m["id"])); flash("أُرسل الرد.")
        else: flash("تعذر إرسال الرد.")
        return redirect(url_for("messages"))
    rows = db.q("SELECT m.*, u.tg_username FROM messages m LEFT JOIN users u USING(tg_id) ORDER BY (reply IS NOT NULL), m.id DESC LIMIT 100")
    return render_template("messages.html", rows=rows)

@app.route("/requests", methods=["GET", "POST"])
def requests_():
    if request.method == "POST":
        action, note = request.form["act"], request.form.get("note", "").strip()[:200]
        status, r = ops.decide(int(request.form["id"]), action, request.form.get("usd"), note)
        if status == "ok":
            tg_send(r["tg_id"], ops.user_message(r, action, note)); flash("تمت الموافقة." if action == "approve" else "تم الرفض.")
        elif status == "already": flash("سبق البتّ في هذا الطلب.")
        return redirect(url_for("requests_"))
    st = request.args.get("s", "pending")
    rows = db.q("SELECT r.*, u.game_login FROM requests r LEFT JOIN users u USING(tg_id) WHERE ?='' OR r.status=? ORDER BY r.id DESC LIMIT 200", (st, st))
    return render_template("requests.html", rows=rows, methods=METHODS_AR, st=st)

METHODS_AR = {"syr": "Syriatel Cash", "shs": "Sham Cash (SYP)", "shu": "Sham Cash (USD)"}

@app.route("/gifts", methods=["GET", "POST"])
def gifts():
    if request.method == "POST":
        try: amt, n = round(float(request.form["amount"]), 2), min(int(request.form.get("n", 1)), 50)
        except ValueError: amt, n = 0, 0
        if amt > 0 and n > 0: flash("الأكواد: " + " ، ".join(db.create_gift(amt) for _ in range(n)))
        else: flash("قيمة غير صالحة.")
        return redirect(url_for("gifts"))
    return render_template("gifts.html", rows=db.q("SELECT * FROM gifts ORDER BY created_at DESC LIMIT 200"))

@app.route("/broadcast", methods=["GET", "POST"])
def broadcast():
    if request.method == "POST" and request.form.get("text", "").strip():
        ids = [r[0] for r in db.q("SELECT tg_id FROM users WHERE banned=0")]
        text = request.form["text"].strip()
        def run():
            for i in ids: tg_send(i, text); time.sleep(0.05)
        threading.Thread(target=run, daemon=True).start()
        flash(f"بدأ الإرسال إلى {len(ids)} مستخدم.")
        return redirect(url_for("broadcast"))
    return render_template("broadcast.html")

LABELS = {"exchange_rate": "سعر الدولار بالليرة (حسب السوق)", "min_deposit": "أقل إيداع/شحن ($)", "min_withdraw": "أقل سحب ($)",
          "syriatel_number": "رقم استلام سيريتل كاش", "sham_number": "معرّف استلام شام كاش",
          "referral_percent": "نسبة الإحالة %", "support_username": "يوزر الدعم (@...)",
          "required_channel": "القناة الإلزامية (@...) — فارغ للتعطيل",
          "referral_min_active": "أقل إحالات نشطة لاحتساب الأرباح",
          "site_rate": "سعر الدولار بعملة الموقع (NSP)", "parent_id": "معرّف الكاشير (PARENT_ID)", "gift_fee_percent": "عمولة الإهداء %"}
GROUPS = [("ربط Ichancy", ["parent_id"]),
          ("الصرف والحدود", ["exchange_rate", "site_rate", "min_deposit", "min_withdraw"]),
          ("استلام الأموال", ["syriatel_number", "sham_number"]),
          ("الإحالات والإهداء", ["referral_percent", "referral_min_active", "gift_fee_percent"]),
          ("التواصل والتحقق", ["support_username", "required_channel"])]
HINTS = {"exchange_rate": "ليرة سورية مقابل 1 دولار، بعملة وسائل الدفع (سيريتل وشام). يُستخدم في الشحن والسحب.",
         "site_rate": "NSP على موقع Ichancy مقابل 1 دولار. اتركه 0 إن كانت وحدة الموقع هي نفس وحدة الدفع. مثال: بعد حذف صفرين اكتب 140 إن كان سعر الدفع 14000.",
         "parent_id": "يظهر في طلبات الموقع باسم affiliateId. يمكن معرفته بالسكربت check_ichancy.py.", "min_deposit": "ينطبق على الشحن وعلى الإيداع إلى حساب أيشانسي.",
         "min_withdraw": "ينطبق على سحب الأموال وعلى السحب من حساب أيشانسي.", "referral_percent": "نسبة من كل إيداع يقوم به المُحال. 0 للتعطيل.",
         "required_channel": "إن كتبتم قناة، لا يُنشأ حساب قبل الاشتراك فيها.",
         "referral_min_active": "إحالة نشطة = مستخدم أجرى تعبئة فعلية. القاعدة الأصلية: 3.", "gift_fee_percent": "تُقتطع من مبلغ الهدية. 0 للتعطيل."}
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for k in LABELS: db.set_(k, request.form.get(k, "").strip())
        ck = request.form.get("ichancy_cookie", "").strip()
        if ck: db.set_("ichancy_cookie", "" if ck == "-" else ck); _cache.update(t=0)
        db.set_("terms_text", request.form.get("terms_text", "")); db.set_("site_support_text", request.form.get("site_support_text", ""))
        db.set_("maintenance", "1" if request.form.get("maintenance") else "0")
        flash("تم الحفظ."); return redirect(url_for("settings"))
    return render_template("settings.html", cookie_set=bool(db.get("ichancy_cookie")), labels=LABELS, groups=GROUPS, hints=HINTS, v={k: db.get(k) for k in [*LABELS, "terms_text", "site_support_text", "maintenance"]})

# ---------------- القوالب ----------------
CSS = """
:root{--ink:#0d2b30;--ink2:#143940;--paper:#f2f5f4;--card:#fff;--tx:#13201e;--mut:#62767a;--bd:#dde5e4;--pri:#0f766e;--pri2:#0b5e58;
--amber:#a66a00;--amberbg:#fdf1d6;--ok:#17703a;--okbg:#e1f3e7;--bad:#b3261e;--badbg:#fbe8e6;--neu:#3d5558;--neubg:#e8eeed}
@media(prefers-color-scheme:dark){:root{--ink:#071a1d;--ink2:#0e2a2f;--paper:#0a1416;--card:#112126;--tx:#e3ecea;--mut:#8ba1a4;--bd:#1e3339;
--pri:#2fb8aa;--pri2:#26a093;--amber:#e3a63c;--amberbg:#2c2410;--ok:#58d98a;--okbg:#0f2b1b;--bad:#f2766d;--badbg:#2d1513;--neu:#a9bfc1;--neubg:#172a2f}}
*{box-sizing:border-box}html{scroll-padding-top:16px}
body{margin:0;background:var(--paper);color:var(--tx);font:15px/1.6 "IBM Plex Sans Arabic","Segoe UI",Tahoma,sans-serif;font-variant-numeric:tabular-nums}
a{color:var(--pri);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--pri);outline-offset:2px}
.shell{display:flex;min-height:100vh}
.side{width:236px;background:var(--ink);color:#cfe0e1;display:flex;flex-direction:column;position:sticky;top:0;height:100vh;flex-shrink:0}
.brand{padding:22px 20px 18px;font-weight:700;font-size:17px;color:#fff;border-bottom:1px solid rgba(255,255,255,.08)}
.brand small{display:block;font-weight:400;font-size:12px;color:#8fb0b3;margin-top:2px}
.side nav{padding:12px 10px;display:flex;flex-direction:column;gap:2px;flex:1;overflow:auto}
.side nav a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;color:#b9d0d2;font-size:14.5px}
.side nav a:hover{background:rgba(255,255,255,.06);text-decoration:none;color:#fff}
.side nav a.on{background:var(--ink2);color:#fff;box-shadow:inset -3px 0 0 #e3a63c}
.side svg{width:18px;height:18px;flex-shrink:0}
.cnt{margin-inline-start:auto;background:#e3a63c;color:#2b1d00;font-size:12px;font-weight:700;border-radius:99px;padding:0 8px;min-width:22px;text-align:center}
.side form{padding:10px;border-top:1px solid rgba(255,255,255,.08)}
.side button{all:unset;box-sizing:border-box;display:flex;align-items:center;gap:10px;width:100%;padding:9px 12px;border-radius:8px;color:#b9d0d2;cursor:pointer;font-size:14.5px}
.side button:hover{background:rgba(255,255,255,.06);color:#fff}
.main{flex:1;min-width:0;padding:28px 32px 48px;max-width:1180px}
h1{font-size:22px;margin:0 0 16px;font-weight:700}h1+.sub{margin-top:-12px}h2{font-size:15.5px;margin:0;font-weight:700}
.sub{color:var(--mut);font-size:13.5px;margin-bottom:22px}
.panel{background:var(--card);border:1px solid var(--bd);border-radius:10px;margin-bottom:18px;overflow:hidden}
.ph{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid var(--bd)}
.pb{padding:18px}.empty{padding:26px 18px;color:var(--mut);text-align:center}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));background:var(--card);border:1px solid var(--bd);border-radius:10px;margin-bottom:18px}
.kpis>div{padding:16px 18px;border-inline-start:1px solid var(--bd)}.kpis>div:first-child{border-inline-start:0}
.kpis .l{color:var(--mut);font-size:13px}.kpis .v{font-size:21px;font-weight:700;margin-top:2px}.kpis .s{color:var(--mut);font-size:12.5px}
.two{display:grid;grid-template-columns:minmax(0,4fr) minmax(0,7fr);gap:18px}
.q{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:center;padding:13px 18px;border-bottom:1px solid var(--bd);box-shadow:inset -4px 0 0 #e3a63c}
.q:last-child{border-bottom:0}.line{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.q b{font-weight:600}.q .m{color:var(--mut);font-size:13px}
.hero{border-color:#e3a63c66}.hero .ph{background:var(--amberbg)}.hero h2{color:var(--amber)}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse}
th{background:var(--paper);color:var(--mut);font-weight:600;font-size:13px;text-align:start;padding:10px 14px;white-space:nowrap}
td{padding:11px 14px;white-space:nowrap;border-top:1px solid var(--bd);font-size:14px;vertical-align:middle}tbody tr:hover{background:var(--paper)}
.b{display:inline-block;padding:1px 10px;border-radius:99px;font-size:12.5px;font-weight:600;white-space:nowrap}
.b-pending{background:var(--amberbg);color:var(--amber)}.b-approved,.b-done{background:var(--okbg);color:var(--ok)}
.b-rejected,.b-failed{background:var(--badbg);color:var(--bad)}.b-neu{background:var(--neubg);color:var(--neu)}
.dt{direction:ltr;unicode-bidi:isolate;white-space:nowrap;display:inline-block}td .dt{display:inline}.pos{color:var(--ok);font-weight:600}.neg{color:var(--bad);font-weight:600}.mut{color:var(--mut)}
input,textarea,select{width:100%;padding:9px 12px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--tx);font:inherit}
input:focus,textarea:focus,select:focus{border-color:var(--pri);outline:0;box-shadow:0 0 0 3px color-mix(in srgb,var(--pri) 20%,transparent)}
label{display:block;font-size:13.5px;font-weight:600;margin:0 0 5px}.hint{font-size:12.5px;color:var(--mut);margin-top:4px}
.btn,button.btn{background:var(--pri);color:#fff;border:0;border-radius:8px;padding:9px 18px;font:inherit;font-weight:600;cursor:pointer;display:inline-block;white-space:nowrap}
.btn:hover{background:var(--pri2);text-decoration:none}.btn.sec{background:transparent;color:var(--tx);border:1px solid var(--bd)}.btn.sec:hover{background:var(--paper)}
.btn.danger{background:transparent;color:var(--bad);border:1px solid var(--bad)}
.fg{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:end}.bar>*{flex:1;min-width:140px}.bar>.btn{flex:0 0 auto}
.note{padding:11px 16px;border-radius:8px;margin-bottom:16px;border:1px solid var(--bd);background:var(--card)}
.note.warn{background:var(--amberbg);border-color:#e3a63c88;color:var(--amber)}.note.ok{background:var(--okbg);color:var(--ok);border-color:transparent}
.chart{display:flex;align-items:flex-end;gap:12px;height:170px;padding:6px 4px 0}.chart .c{flex:1;text-align:center}
.chart .bars{height:140px;display:flex;align-items:flex-end;justify-content:center;gap:4px}.chart .bars i{display:block;width:34%;min-height:2px;border-radius:4px 4px 0 0}
.chart .d{font-size:12px;color:var(--mut);margin-top:6px}.lg{display:flex;gap:16px;font-size:13px;color:var(--mut)}.lg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-inline-end:6px}
.tabs{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}.tabs a{padding:6px 14px;border-radius:99px;border:1px solid var(--bd);color:var(--tx);font-size:14px;background:var(--card)}
.tabs a.on{background:var(--ink);color:#fff;border-color:var(--ink)}.tabs a:hover{text-decoration:none}
.req{padding:16px 18px;border-top:1px solid var(--bd)}.req:first-child{border-top:0}.req .top{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.req form{margin-top:12px}.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:12px 0}.kv .k{font-size:12.5px;color:var(--mut)}.kv .vv{font-weight:600}
.login{min-height:100vh;display:grid;place-items:center;background:var(--ink);padding:20px}.login .panel{width:100%;max-width:380px;margin:0}
@media(max-width:900px){.shell{display:block}.side{width:auto;height:auto;position:static;flex-direction:row;align-items:center;overflow-x:auto}
.brand{border:0;padding:12px 16px;white-space:nowrap}.brand small{display:none}.side nav{flex-direction:row;padding:8px;overflow:visible}.side nav a{white-space:nowrap}
.side form{border:0;padding:8px}.main{padding:20px 16px 40px}.two{grid-template-columns:1fr}.side nav a.on{box-shadow:inset 0 -3px 0 #e3a63c}}
"""
BASE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block t %}لوحة التحكم{% endblock %}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;600;700&display=swap" rel="stylesheet">
<style>""" + CSS + """</style></head><body>
{% if session.ok %}<div class="shell"><aside class="side"><div class="brand">لوحة الكاشير<small>إدارة الحسابات والطلبات</small></div>
<nav>{% for e,u,l,i,n in nav %}<a href="{{u}}" class="{{'on' if ep==e}}">{{ico(i)}}<span>{{l}}</span>{% if n %}<span class="cnt">{{n}}</span>{% endif %}</a>{% endfor %}</nav>
<form method="post" action="/logout"><input type="hidden" name="_t" value="{{tok}}"><button type="submit">{{ico('out')}}<span>تسجيل الخروج</span></button></form></aside>
<main class="main">{% for m in get_flashed_messages() %}<div class="note ok">{{m}}</div>{% endfor %}{% block c %}{% endblock %}</main></div>
{% else %}{% block l %}{% endblock %}{% endif %}</body></html>"""

def T(title, body):
    return "{% extends 'base.html' %}{% block t %}" + title + "{% endblock %}{% block c %}<h1>" + title + "</h1>" + body + "{% endblock %}"

TX_TABLE = """<div class="tw"><table><thead><tr><th>التاريخ</th><th>المستخدم</th><th>النوع</th><th>الدولار</th><th>NSP</th><th>الحالة</th><th>ملاحظة</th></tr></thead><tbody>
{% for r in ROWS %}<tr><td class="mut"><span class="dt">{{r.created_at[5:16]}}</span></td><td><a href="/user/{{r.tg_id}}">{{r['game_login'] or r.tg_id}}</a></td><td>{{kind_ar.get(r.kind,r.kind)}}</td>
<td class="{{'pos' if r.usd>0 else 'neg' if r.usd<0 else 'mut'}}"><span class="dt">{{'%+.2f'|format(r.usd) if r.usd else '—'}}</span></td><td>{{'{:,}'.format(r.nsp) if r.nsp else '—'}}</td>
<td><span class="b b-{{r.status}}">{{st_ar.get(r.status,r.status)}}</span></td><td class="mut">{{r.note or ''}}</td></tr>
{% else %}<tr><td colspan="7" class="empty">لا توجد عمليات بعد.</td></tr>{% endfor %}</tbody></table></div>"""
def TXT(rows): return TX_TABLE.replace("ROWS", rows)

TX_COMPACT = """<div class="tw"><table><thead><tr><th>الوقت</th><th>المستخدم</th><th>العملية</th><th>الدولار</th><th>الحالة</th></tr></thead><tbody>
{% for r in recent %}<tr><td class="mut"><span class="dt">{{r.created_at[5:16]}}</span></td><td><a href="/user/{{r.tg_id}}">{{r['game_login'] or r.tg_id}}</a></td><td>{{kind_ar.get(r.kind,r.kind)}}</td>
<td class="{{'pos' if r.usd>0 else 'neg' if r.usd<0 else 'mut'}}"><span class="dt">{{'%+.2f'|format(r.usd) if r.usd else '—'}}</span></td>
<td><span class="b b-{{r.status}}">{{st_ar.get(r.status,r.status)}}</span></td></tr>
{% else %}<tr><td colspan="5" class="empty">لا توجد عمليات بعد.</td></tr>{% endfor %}</tbody></table></div>"""
TEMPLATES = {"base.html": BASE,
"login.html": """{% extends 'base.html' %}{% block t %}تسجيل الدخول{% endblock %}{% block l %}<div class="login"><div class="panel"><div class="pb">
<h1>تسجيل الدخول</h1><div class="sub">لوحة الكاشير</div>{% for m in get_flashed_messages() %}<div class="note warn">{{m}}</div>{% endfor %}
<form method="post"><input type="hidden" name="_t" value="{{tok}}"><label for="u">اسم المستخدم</label><input id="u" name="u" required autofocus autocomplete="username">
<div style="height:14px"></div><label for="p">كلمة المرور</label><input id="p" name="p" type="password" required autocomplete="current-password">
<div style="height:18px"></div><button class="btn" style="width:100%">دخول</button></form></div></div></div>{% endblock %}""",

"home.html": "{% extends 'base.html' %}{% block t %}نظرة عامة{% endblock %}{% block c %}<h1>نظرة عامة</h1><div class=\"sub\">ما يحتاج قراراً منك الآن، ثم أرقام اليوم.</div>" + """
{% if rate <= 1 %}<div class="note warn">سعر الصرف غير مضبوط. افتح الإعدادات وأدخل سعر الدولار بالليرة.</div>{% endif %}
{% if not mock and agent is none %}<div class="note warn">تعذر الاتصال بـ Ichancy. غالباً انتهت صلاحية الكوكيز: الصقوا كوكيز جديدة من الإعدادات.</div>{% endif %}{% if mock %}<div class="note warn">وضع تجريبي: لا يوجد اتصال حقيقي مع Ichancy لأن ICHANCY_COOKIE فارغ.</div>{% endif %}
<section class="panel hero"><div class="ph"><h2>بانتظار المراجعة ({{pending|length}})</h2><a href="/requests">عرض كل الطلبات</a></div>
{% for r in pending %}<div class="q"><span class="b b-neu">{{'شحن' if r.kind=='topup' else 'سحب'}}</span>
<div><div class="line"><b>{{r['game_login'] or r.tg_id}}</b><span class="b b-neu">{{methods[r.method]}}</span><b class="dt">{{'{:,.0f}'.format(r.amount)}}</b><span class="m dt">{{'%.2f'|format(r.usd)}}$</span></div>
<div class="line m"><span class="dt">{{r.created_at[5:16]}}</span><span>{{'رقم العملية' if r.kind=='topup' else 'الحساب المستلم'}}: <span class="dt">{{r.ref}}</span></span></div></div>
<a class="btn" href="/requests#r{{r.id}}">مراجعة</a></div>
{% else %}<div class="empty">لا توجد طلبات معلّقة. سيظهر هنا كل طلب شحن أو سحب جديد.</div>{% endfor %}</section>
<section class="kpis"><div><div class="l">المستخدمون</div><div class="v">{{s.users}}</div><div class="s">{{s.accounts}} لديهم حساب، {{s.today}} اليوم</div></div>
<div><div class="l">أرصدة المحافظ</div><div class="v"><span class="dt">{{'%.2f'|format(s.wallets)}}$</span></div></div>
<div><div class="l">رصيد الوكيل (NSP)</div><div class="v">{{ '{:,.0f}'.format(agent) if agent is not none else '—' }}</div></div>
<div><div class="l">إيداعات اليوم (NSP)</div><div class="v">{{'{:,}'.format(s.dep)}}</div></div>
<div><div class="l">سحوبات اليوم (NSP)</div><div class="v">{{'{:,}'.format(s.wd)}}</div></div>
<div><div class="l">رسائل بلا رد</div><div class="v">{{s.unread}}</div><div class="s">{{s.failed}} عملية فاشلة</div></div></section>
<div class="two"><section class="panel"><div class="ph"><h2>حركة آخر 7 أيام (NSP)</h2></div><div class="pb"><div class="chart">
{% for x in series %}<div class="c"><div class="bars"><i style="height:{{x.hd}}%;background:var(--pri)" title="إيداع {{x.dep}}"></i><i style="height:{{x.hw}}%;background:#e3a63c" title="سحب {{x.wd}}"></i></div><div class="d">{{x.d}}</div></div>{% endfor %}</div>
<div class="lg" style="margin-top:12px"><span><i style="background:var(--pri)"></i>إيداع</span><span><i style="background:#e3a63c"></i>سحب</span></div></div></section>
<section class="panel"><div class="ph"><h2>آخر العمليات</h2><a href="/transactions">الكل</a></div>""" + TXT("recent") + "</section></div>{% endblock %}",

"users.html": T("المستخدمون", """<form class="bar" style="margin-bottom:16px"><div><label for="q">بحث</label><input id="q" name="q" value="{{term}}" placeholder="آيدي تيليغرام، يوزر، أو اسم الحساب"></div><button class="btn">بحث</button></form>
<section class="panel"><div class="tw"><table><thead><tr><th>الآيدي</th><th>اليوزر</th><th>حساب اللعبة</th><th>رقم اللاعب</th><th>المحفظة</th><th>التسجيل</th><th>الحالة</th></tr></thead><tbody>
{% for r in rows %}<tr><td><a href="/user/{{r.tg_id}}">{{r.tg_id}}</a></td><td>{{r.tg_username or '—'}}</td><td>{{r.game_login or '—'}}</td><td>{{r.player_id or '—'}}</td>
<td><b><span class="dt">{{'%.2f'|format(r.wallet)}}$</span></b></td><td class="mut"><span class="dt">{{r.created_at[:16]}}</span></td><td>{% if r.banned %}<span class="b b-rejected">محظور</span>{% else %}<span class="b b-done">نشط</span>{% endif %}</td></tr>
{% else %}<tr><td colspan="7" class="empty">لا يوجد مستخدمون مطابقون.</td></tr>{% endfor %}</tbody></table></div></section>"""),

"user.html": T("{{u.game_login or 'مستخدم بدون حساب'}}", """<div class="sub">آيدي تيليغرام {{u.tg_id}}، يوزر {{u.tg_username or '—'}}</div>
<section class="panel"><div class="pb"><div class="kv"><div><div class="k">رصيد المحفظة</div><div class="vv"><span class="dt">{{'%.2f'|format(u.wallet)}}$</span></div></div>
<div><div class="k">رقم اللاعب</div><div class="vv">{{u.player_id or '—'}}</div></div><div><div class="k">عدد المُحالين</div><div class="vv">{{refs}}</div></div>
<div><div class="k">المُحيل</div><div class="vv">{{u.referrer or '—'}}</div></div><div><div class="k">الحالة</div><div class="vv">{{'محظور' if u.banned else 'نشط'}}</div></div></div></div></section>
<section class="panel"><div class="ph"><h2>تعديل الرصيد</h2></div><div class="pb"><form method="post" class="bar"><input type="hidden" name="_t" value="{{tok}}"><input type="hidden" name="act" value="adjust">
<div><label for="amount">المبلغ بالدولار</label><input id="amount" name="amount" required placeholder="موجب للإضافة، سالب للخصم"></div><div><label for="note">ملاحظة</label><input id="note" name="note"></div>
<button class="btn">تنفيذ</button></form>
<form method="post" style="margin-top:14px"><input type="hidden" name="_t" value="{{tok}}"><input type="hidden" name="act" value="ban"><button class="btn {{'sec' if u.banned else 'danger'}}">{{'إلغاء الحظر' if u.banned else 'حظر المستخدم'}}</button></form></div></section>
<section class="panel"><div class="ph"><h2>عمليات المستخدم</h2></div>""" + TXT("txs") + "</section>"),

"tx.html": T("المعاملات", """<form class="bar" style="margin-bottom:16px"><div><label for="kind">نوع العملية</label><select id="kind" name="kind"><option value="">كل الأنواع</option>
{% for k,v in kind_ar.items() %}<option value="{{k}}" {{'selected' if k==kind}}>{{v}}</option>{% endfor %}</select></div><button class="btn">تصفية</button></form>
<section class="panel">""" + TXT("rows") + "</section>"),

"requests.html": T("الطلبات", """<div class="tabs">{% for k,l in [('pending','قيد المراجعة'),('approved','مقبولة'),('rejected','مرفوضة'),('','الكل')] %}<a href="/requests?s={{k}}" class="{{'on' if st==k}}">{{l}}</a>{% endfor %}</div>
<section class="panel">{% for r in rows %}<div class="req" id="r{{r.id}}"><div class="top"><b>طلب {{'شحن' if r.kind=='topup' else 'سحب'}} #{{r.id}}</b>
<span class="b b-{{r.status}}">{{st_ar[r.status]}}</span><span class="mut"><span class="dt">{{r.created_at[:16]}}</span></span></div>
<div class="kv"><div><div class="k">المستخدم</div><div class="vv"><a href="/user/{{r.tg_id}}">{{r['game_login'] or r.tg_id}}</a></div></div>
<div><div class="k">الطريقة</div><div class="vv">{{methods[r.method]}}</div></div><div><div class="k">المبلغ</div><div class="vv">{{'{:,.0f}'.format(r.amount)}}</div></div>
<div><div class="k">يعادل بالدولار</div><div class="vv"><span class="dt">{{'%.2f'|format(r.usd)}}$</span></div></div><div><div class="k">{{'رقم العملية' if r.kind=='topup' else 'الحساب المستلم'}}</div><div class="vv">{{r.ref}}</div></div></div>
{% if r.status=='pending' %}<form method="post" class="bar"><input type="hidden" name="_t" value="{{tok}}"><input type="hidden" name="id" value="{{r.id}}">
{% if r.kind=='topup' %}<div><label>المبلغ المعتمد بالدولار</label><input name="usd" value="{{'%.2f'|format(r.usd)}}"></div>{% endif %}
<div><label>ملاحظة أو سبب الرفض</label><input name="note"></div>
<button class="btn" name="act" value="approve">{{'اعتماد وشحن المحفظة' if r.kind=='topup' else 'تم التحويل'}}</button><button class="btn danger" name="act" value="reject">رفض</button></form>
{% elif r.note %}<div class="mut">{{r.note}}</div>{% endif %}</div>
{% else %}<div class="empty">لا توجد طلبات في هذا التبويب.</div>{% endfor %}</section>"""),

"messages.html": T("الرسائل", """{% for r in rows %}<section class="panel"><div class="ph"><div><b>{{r.tg_username or r.tg_id}}</b> <span class="mut">رسالة #{{r.id}}، <span class="dt">{{r.created_at[:16]}}</span></span></div>
<span class="b b-{{'approved' if r.reply else 'pending'}}">{{'تم الرد' if r.reply else 'بلا رد'}}</span></div><div class="pb"><p style="margin:0 0 12px">{{r.text}}</p>
{% if r.reply %}<div class="note ok" style="margin:0">ردّك: {{r.reply}}</div>{% else %}<form method="post"><input type="hidden" name="_t" value="{{tok}}"><input type="hidden" name="id" value="{{r.id}}">
<label for="rp{{r.id}}">الرد</label><textarea id="rp{{r.id}}" name="reply" rows="2" required></textarea><div style="height:10px"></div><button class="btn">إرسال الرد</button></form>{% endif %}</div></section>
{% else %}<section class="panel"><div class="empty">لا توجد رسائل. ستظهر هنا رسائل المستخدمين الموجهة للإدارة.</div></section>{% endfor %}"""),

"gifts.html": T("الهدايا", """<section class="panel"><div class="ph"><h2>إنشاء أكواد هدية</h2></div><div class="pb"><form method="post" class="bar"><input type="hidden" name="_t" value="{{tok}}">
<div><label for="a">القيمة بالدولار</label><input id="a" name="amount" required></div><div><label for="n">عدد الأكواد</label><input id="n" name="n" type="number" value="1" min="1" max="50"></div><button class="btn">إنشاء</button></form></div></section>
<section class="panel"><div class="tw"><table><thead><tr><th>الكود</th><th>القيمة</th><th>أنشأه</th><th>الحالة</th><th>التاريخ</th></tr></thead><tbody>
{% for r in rows %}<tr><td><b>{{r.code}}</b></td><td><span class="dt">{{r.amount}}$</span></td><td>{{r.created_by or 'الإدارة'}}</td><td>{% if r.redeemed_by %}<span class="b b-neu">استُخدم بواسطة {{r.redeemed_by}}</span>{% else %}<span class="b b-done">متاح</span>{% endif %}</td><td class="mut"><span class="dt">{{r.created_at[:16]}}</span></td></tr>
{% else %}<tr><td colspan="5" class="empty">لا توجد أكواد بعد.</td></tr>{% endfor %}</tbody></table></div></section>"""),

"broadcast.html": T("بث جماعي", """<section class="panel"><div class="pb"><form method="post"><input type="hidden" name="_t" value="{{tok}}"><label for="t">نص الرسالة</label>
<textarea id="t" name="text" rows="6" required></textarea><div class="hint">تُرسل إلى كل المستخدمين غير المحظورين.</div><div style="height:14px"></div>
<button class="btn" onclick="return confirm('إرسال الرسالة إلى كل المستخدمين؟')">إرسال للجميع</button></form></div></section>"""),

"settings.html": T("الإعدادات", """<form method="post"><input type="hidden" name="_t" value="{{tok}}">
{% for title,keys in groups %}<section class="panel"><div class="ph"><h2>{{title}}</h2></div><div class="pb"><div class="fg">
{% for k in keys %}<div><label for="{{k}}">{{labels[k]}}</label><input id="{{k}}" name="{{k}}" value="{{v[k]}}">{% if hints[k] %}<div class="hint">{{hints[k]}}</div>{% endif %}</div>{% endfor %}{% if title=='ربط Ichancy' %}<div style="grid-column:1/-1"><label for="ck">كوكيز جلسة الكاشير</label>
<textarea id="ck" name="ichancy_cookie" rows="3" autocomplete="off" placeholder="{{'محفوظة. الصق كوكيز جديدة للاستبدال، أو اكتب - للحذف' if cookie_set else 'الصق هنا سلسلة Cookie كاملة من المتصفح'}}"></textarea>
<div class="hint">{{'الحالة: محفوظة' if cookie_set else 'الحالة: غير مضبوطة، والبوت يعمل بوضع تجريبي'}}. لا تُعرض الكوكيز بعد الحفظ. تنتهي صلاحيتها دورياً فجدّدوها من هنا دون إعادة تشغيل.</div></div>{% endif %}</div></div></section>{% endfor %}
<section class="panel"><div class="ph"><h2>نصوص وتشغيل</h2></div><div class="pb"><label for="g">نص الشروط والأحكام</label><textarea id="g" name="terms_text" rows="9">{{v.terms_text}}</textarea>
<div style="height:14px"></div><label for="s">نص دعم الموقع (مشكلة تقنية ضمن الموقع)</label><textarea id="s" name="site_support_text" rows="4">{{v.site_support_text}}</textarea>
<div style="height:14px"></div><label style="display:flex;gap:10px;align-items:center;font-weight:400"><input type="checkbox" name="maintenance" {{'checked' if v.maintenance=='1'}} style="width:auto"> وضع الصيانة: يوقف البوت للمستخدمين مؤقتاً</label></div></section>
<button class="btn">حفظ الإعدادات</button></form>"""),
}
app.jinja_loader = DictLoader(TEMPLATES)
