"""منطق مشترك بين البوت والداشبورد: قبول/رفض الطلبات، الإحالات، تشفير كلمات المرور."""
import os, base64, hashlib, logging
from cryptography.fernet import Fernet
import db

log = logging.getLogger("ops")

def _fernet():
    seed = os.getenv("SECRET_KEY") or "insecure-default-change-me"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()))
def enc(text): return _fernet().encrypt(text.encode()).decode()
def dec(token):
    try: return _fernet().decrypt(token.encode()).decode() if token else None
    except Exception: return None

METHODS = {"syr": ("Syriatel Cash 🟢", "SYP", "syriatel_number"),
           "shs": ("Sham Cash (SYP) 🇸🇾", "SYP", "sham_number"),
           "shu": ("Sham Cash (USD) 💲", "USD", "sham_number")}

def decide(rid, action, usd=None, note=""):
    """يبتّ في طلب معلّق. يعيد (الحالة, الطلب) والحالة: ok | missing | already."""
    r = db.q("SELECT * FROM requests WHERE id=?", (rid,), one=True)
    if not r: return "missing", None
    if r["status"] != "pending": return "already", r
    stamp = "decided_at=datetime('now','localtime')"
    if action == "approve":
        try: val = round(float(usd), 2) if usd not in (None, "") else r["usd"]
        except (TypeError, ValueError): val = r["usd"]
        if r["kind"] != "topup": val = r["usd"]
        if db.x(f"UPDATE requests SET status='approved', usd=?, note=?, {stamp} WHERE id=? AND status='pending'", (val, note, rid))[0] != 1:
            return "already", r
        if r["kind"] == "topup":
            db.wallet_add(r["tg_id"], val); db.log(r["tg_id"], "topup", val, 0, note=f"#{rid}")
    else:
        if db.x(f"UPDATE requests SET status='rejected', note=?, {stamp} WHERE id=? AND status='pending'", (note, rid))[0] != 1:
            return "already", r
        if r["kind"] == "payout":
            db.wallet_add(r["tg_id"], r["usd"]); db.log(r["tg_id"], "payout_refund", r["usd"], 0, note=f"#{rid}")
    return "ok", db.q("SELECT * FROM requests WHERE id=?", (rid,), one=True)

def user_message(r, action, note=""):
    kind = "الشحن" if r["kind"] == "topup" else "السحب"
    if action == "approve":
        return (f"✅ تمت الموافقة على طلب {kind} #{r['id']}.\nتم تحديث رصيد محفظتك: +{r['usd']}$" if r["kind"] == "topup"
                else f"✅ تم تنفيذ طلب السحب #{r['id']} وإرسال المبلغ إلى حسابك.")
    return (f"❌ تم رفض طلب {kind} #{r['id']}." + (f"\nالسبب: {note}" if note else "") +
            ("\nأُعيد المبلغ إلى محفظتك." if r["kind"] == "payout" else "\nللاستفسار تواصل معنا."))

def active_referrals(tg):
    return db.q("""SELECT count(*) FROM users u WHERE u.referrer=? AND EXISTS(
        SELECT 1 FROM tx WHERE tx.tg_id=u.tg_id AND tx.kind IN ('topup','deposit_game') AND tx.status='done')""", (tg,), one=True)[0]

def pay_referral(user, usd):
    """عمولة الإحالة: فقط إذا بلغ المُحيل الحد الأدنى من الإحالات النشطة. يعيد (المُحيل, العمولة) أو None."""
    ref, pct = user["referrer"], db.getf("referral_percent")
    if not ref or pct <= 0 or active_referrals(ref) < db.getf("referral_min_active"): return None
    bonus = round(usd * pct / 100, 2)
    if bonus > 0 and db.wallet_add(ref, bonus):
        db.log(ref, "referral", bonus, 0, note=f"من {user['tg_id']}")
        return ref, bonus
