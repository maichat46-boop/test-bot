"""طبقة قاعدة البيانات (SQLite) — كل العمليات المالية ذرّية."""
import os, sqlite3, threading, secrets

DB_PATH = os.getenv("DB_PATH", "data.db")
_lock = threading.RLock()
_c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30, isolation_level=None)
_c.row_factory = sqlite3.Row
_c.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(
  tg_id INTEGER PRIMARY KEY, tg_username TEXT, game_login TEXT UNIQUE, player_id TEXT,
  wallet REAL NOT NULL DEFAULT 0, referrer INTEGER, banned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS tx(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER NOT NULL, kind TEXT NOT NULL,
  usd REAL NOT NULL DEFAULT 0, nsp INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'done',
  note TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS gifts(
  code TEXT PRIMARY KEY, amount REAL NOT NULL, created_by INTEGER NOT NULL DEFAULT 0,
  redeemed_by INTEGER, redeemed_at TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER NOT NULL, text TEXT NOT NULL, reply TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')), replied_at TEXT);
CREATE TABLE IF NOT EXISTS requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER NOT NULL, kind TEXT NOT NULL, method TEXT NOT NULL,
  amount REAL NOT NULL, usd REAL NOT NULL, ref TEXT, status TEXT NOT NULL DEFAULT 'pending', note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')), decided_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
""")

for _ddl in ("ALTER TABLE users ADD COLUMN email TEXT", "ALTER TABLE users ADD COLUMN pw_enc TEXT",
             "ALTER TABLE gifts ADD COLUMN to_tg INTEGER"):
    try: _c.execute(_ddl)
    except sqlite3.OperationalError: pass  # العمود موجود مسبقاً

TERMS_DEFAULT = (
    "الشروط والأحكام\n\n"
    "باستخدامك البوت فأنت توافق على الشروط التالية، ويحق لك الاعتراض عند مواجهة أي مشكلة خارجة عنها. "
    "يرجى قراءتها قبل الاستخدام لتجربة آمنة.\n\n"
    "البوت مخصص لإنشاء الحسابات والسحب والتعبئة الفورية لحسابات موقع Ichancy.\n\n"
    "1) منع الحسابات المتعددة:\nإنشاء أكثر من حساب للشخص الواحد مخالف للقوانين، وقد يؤدي إلى حظر الحسابات المرتبطة وتجميد أرصدتها.\n\n"
    "2) تبديل طرق الدفع غير مسموح:\nلا يُسمح بشحن رصيد وسحبه بغرض التبديل بين وسائل الدفع. عند اكتشاف ذلك يُسحب الرصيد ويُتحفظ عليه دون إشعار مسبق.\n\n"
    "3) شروط أرباح الإحالات:\nتُحتسب أرباح الإحالة فقط بعد تسجيل 3 إحالات نشطة أو أكثر (أي قاموا بالتعبئة الفعلية).\n\n"
    "⛔️ تنبيه:\nأي محاولة للتحايل أو مخالفة الشروط تؤدي إلى إيقاف الحساب وتجميد الأرصدة.")
SITE_SUPPORT_DEFAULT = (
    "في حال ورود مشكلة تقنية ضمن الموقع، يرجى التواصل مع الدعم الرسمي للموقع:\n"
    "https://direct.lc.chat/16220229/\n\nأو عبر صفحة الموقع الرسمية على فيسبوك:\n"
    "https://www.facebook.com/ichancy.co")

DEFAULTS = {
    "exchange_rate": "14000",       # سعر الدولار بالليرة السورية حسب السوق (حدّثه من الداشبورد)
    "min_deposit": "25",        # أقل إيداع/شحن بالدولار
    "min_withdraw": "25",       # أقل سحب بالدولار
    "syriatel_number": "",      # رقم/كود استلام سيريتل كاش
    "sham_number": "",          # رقم/معرّف استلام شام كاش
    "referral_percent": "0",    # نسبة المُحيل من كل إيداع للمُحال (%)
    "maintenance": "0",
    "support_username": "",
    "required_channel": "",     # مثال: @mychannel — اتركه فارغاً لتعطيل التحقق
    "site_rate": "0",           # وحدات NSP على الموقع مقابل 1$ (0 = نفس سعر الصرف). للعملة الجديدة اضبطه.
    "parent_id": "",            # معرّف حساب الكاشير في Ichancy (يغني عن PARENT_ID في .env)
    "ichancy_cookie": "",       # كوكيز جلسة الكاشير (سرّية، لا تُعرض في الداشبورد)
    "referral_min_active": "3",  # أقل عدد إحالات نشطة لاحتساب أرباح الإحالة
    "gift_fee_percent": "0",     # عمولة الإهداء %
    "terms_text": TERMS_DEFAULT,
    "site_support_text": SITE_SUPPORT_DEFAULT,
}
KIND_AR = {
    "deposit_game": "إيداع إلى حساب أيشانسي", "withdraw_game": "سحب من حساب أيشانسي",
    "admin_adjust": "تعديل من الإدارة", "gift_send": "إهداء رصيد", "gift_redeem": "استرداد هدية",
    "referral": "عمولة إحالة", "gift_fee": "عمولة إهداء", "topup": "شحن المحفظة", "payout": "سحب أموال (قيد المعالجة)", "payout_refund": "إعادة رصيد سحب مرفوض", "deposit_game_failed": "إيداع فاشل (أُعيد الرصيد)",
}

# ترحيل: إن كان سعر الصرف ما زال القيمة الافتراضية القديمة (1) نضبطه على 14000
_c.execute("UPDATE settings SET value='14000' WHERE key='exchange_rate' AND value IN ('1','1.0')")

def q(sql, args=(), one=False):
    with _lock:
        rows = _c.execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows

def x(sql, args=()):
    with _lock:
        cur = _c.execute(sql, args)
        return cur.rowcount, cur.lastrowid

# ---- settings
def get(key):
    r = q("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return r["value"] if r else DEFAULTS[key]
def getf(key):
    try: return float(get(key))
    except ValueError: return float(DEFAULTS[key]) if DEFAULTS[key].replace('.','',1).isdigit() else 0.0
def site_rate():
    """سعر 1$ بوحدات الموقع (NSP). إن لم يُضبط يُستخدم سعر الصرف العام."""
    return getf("site_rate") or getf("exchange_rate")

def set_(key, value):
    x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

# ---- بذر الإعدادات من متغيرات البيئة: SET_<KEY> (مفيد على استضافات يُمسح فيها القرص)
for _k in DEFAULTS:
    _v = os.getenv("SET_" + _k.upper())
    if _v is not None and not q("SELECT 1 FROM settings WHERE key=?", (_k,), one=True):
        set_(_k, _v)

# ---- users
def get_user(tg):
    return q("SELECT * FROM users WHERE tg_id=?", (tg,), one=True)
def upsert_user(tg, username, referrer=None):
    if not get_user(tg):
        if referrer == tg or not (referrer and get_user(referrer)): referrer = None
        x("INSERT INTO users(tg_id,tg_username,referrer) VALUES(?,?,?)", (tg, username, referrer))
    else:
        x("UPDATE users SET tg_username=? WHERE tg_id=?", (username, tg))
    return get_user(tg)
def set_account(tg, login, pid, email=None, pw_enc=None):
    x("UPDATE users SET game_login=?, player_id=?, email=?, pw_enc=? WHERE tg_id=?", (login, pid, email, pw_enc, tg))
def wallet_add(tg, usd):
    return x("UPDATE users SET wallet=round(wallet+?,2) WHERE tg_id=?", (usd, tg))[0] == 1
def wallet_take(tg, usd):
    """يخصم فقط إذا كان الرصيد كافياً — عملية ذرّية."""
    return x("UPDATE users SET wallet=round(wallet-?,2) WHERE tg_id=? AND wallet>=?", (usd, tg, usd))[0] == 1
def log(tg, kind, usd=0.0, nsp=0, status="done", note=None):
    return x("INSERT INTO tx(tg_id,kind,usd,nsp,status,note) VALUES(?,?,?,?,?,?)", (tg, kind, usd, int(nsp), status, note))[1]

# ---- gifts
def create_gift(amount, by=0, to_tg=None):
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(12))
    x("INSERT INTO gifts(code,amount,created_by,to_tg) VALUES(?,?,?,?)", (code, amount, by, to_tg))
    return code
def redeem_gift(code, tg):
    """يعيد المبلغ أو None. الاسترداد ذرّي: الكود يُستخدم مرة واحدة فقط."""
    code = code.strip().upper()
    n, _ = x("UPDATE gifts SET redeemed_by=?, redeemed_at=datetime('now','localtime') WHERE code=? AND redeemed_by IS NULL AND (to_tg IS NULL OR to_tg=?)", (tg, code, tg))
    if n != 1: return None
    amt = q("SELECT amount FROM gifts WHERE code=?", (code,), one=True)["amount"]
    wallet_add(tg, amt); log(tg, "gift_redeem", amt, note=code)
    return amt
