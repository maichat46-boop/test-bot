"""بوت تيليغرام (Test): نفس وظائف البوت الأصلي بتصميم مختلف."""
import os, re, html, asyncio, logging, random, string, math
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M, BotCommand
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler, MessageHandler,
                          ConversationHandler as CH, ContextTypes, filters)
import db, ops
from ichancy import Ichancy

log = logging.getLogger("bot")
api = Ichancy()
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0") or 0)
ADMIN_CHAT = int(os.getenv("ADMIN_CHAT_ID", "0") or 0) or ADMIN_ID   # مجموعة اختيارية لاستقبال الطلبات
TITLE = os.getenv("BOT_TITLE", "Test")
END = CH.END
METHODS = ops.METHODS

def b(text, data): return B(text, callback_data=data)
BACK = M([[b("🏠 القائمة الرئيسية", "menu")]])

# ---------------------------------------------------------------- واجهات
def menu_kb():
    return M([[b("⚡️ حساب Ichancy", "ichancy")],
              [b("شحن رصيد 📥", "deposit"), b("سحب رصيد 📤", "withdrawal")],
              [b("نظام الإحالات 💰", "referral")],
              [b("إهداء رصيد 🎁", "send_gift"), b("كود هدية 🎁", "reseive_gift")],
              [b("رسالة للأدمن 📨", "admin_message"), b("تواصل معنا ✉️", "contact_us")],
              [b("السجل 📜", "log"), b("الشروحات 📝", "guides")],
              [b("الشروط والأحكام 📌", "terms_and_conditions")]])

def welcome(u):
    return f"👋 أهلاً بك في بوت {TITLE}\n\n💼 رصيد محفظتك: {u['wallet']:.2f}$\n\nاختر من القائمة:"

def methods_kb(prefix, only_configured=False):
    """only_configured: لا تعرض إلا الطرق التي أُدخل لها رقم استلام (للشحن)."""
    items = [(k, v) for k, v in METHODS.items() if not only_configured or db.get(v[2])]
    return M([[b(v[0], f"{prefix}_{k}")] for k, v in items] + [[b("🏠 القائمة الرئيسية", "menu")]])

async def say(update, text, kb=None, h=False):
    """من زر: يعدّل الرسالة نفسها. من رسالة نصية: يرسل رسالة جديدة."""
    pm = "HTML" if h else None
    q = update.callback_query
    if q:
        try:
            await q.edit_message_text(text, reply_markup=kb, parse_mode=pm); return
        except Exception: pass
    await update.effective_chat.send_message(text, reply_markup=kb, parse_mode=pm)

async def gate(update, ctx=None):
    eu = update.effective_user
    ref = None
    if ctx is not None and getattr(ctx, "args", None) and ctx.args[0].startswith("ref_"):
        try: ref = int(ctx.args[0][4:])
        except ValueError: pass
    u = db.upsert_user(eu.id, eu.username, ref)
    if u["banned"]:
        await update.effective_chat.send_message("⛔ تم تقييد حسابك. تواصل مع الدعم."); return None
    if db.get("maintenance") == "1" and eu.id != ADMIN_ID:
        await update.effective_chat.send_message("🛠 البوت في صيانة مؤقتة، حاول لاحقاً."); return None
    return u

async def notify_admin(ctx, text, kb=None):
    if ADMIN_CHAT:
        try: await ctx.bot.send_message(ADMIN_CHAT, text, reply_markup=kb)
        except Exception as e: log.warning("notify_admin: %s", e)

def fresh(u): return db.get_user(u["tg_id"])

# ---------------------------------------------------------------- الأوامر
async def start(update: Update, ctx):
    u = await gate(update, ctx)
    if u: await say(update, welcome(u), menu_kb())
    return END

async def balance_cmd(update: Update, ctx):
    u = await gate(update)
    if u:
        await say(update, f"💼 رصيد المحفظة: {u['wallet']:.2f}$\n🆔 معرّفك على تيليغرام: <code>{u['tg_id']}</code>\n"
                          "(استخدم هذا المعرّف لاستلام الهدايا)", BACK, h=True)
    return END

# ---------------------------------------------------------------- مركز حساب Ichancy
async def hub(update, ctx, u):
    if not u["game_login"]:
        await say(update, "⚡️ <b>حساب Ichancy</b>\n\nليس لديك حساب بعد. أنشئ حسابك الآن:",
                  M([[b("إنشاء حساب جديد ➕", "create_account")], [b("🏠 القائمة الرئيسية", "menu")]]), h=True)
        return
    bal = await asyncio.to_thread(api.player_balance, u["player_id"])
    pw = ops.dec(u["pw_enc"]) or "غير محفوظة"
    await say(update,
              "⚡️ <b>حساب Ichancy</b>\n\n🌐 https://www.ichancy.com/ar\n"
              f"👤 الدخول: <code>{html.escape(u['game_login'])}</code>\n📧 الإيميل: <code>{html.escape(u['email'] or '—')}</code>\n"
              f"🔒 كلمة السر: <code>{html.escape(pw)}</code>\n🆔 رقم اللاعب: <code>{u['player_id']}</code>\n\n"
              f"🎰 رصيد الحساب: {'غير متاح' if bal is None else f'{int(bal):,}'} NSP\n💼 رصيد المحفظة: {u['wallet']:.2f}$\n"
              f"💱 سعر الصرف: 1$ = {db.site_rate():,.0f} NSP",
              M([[b("سحب من الحساب 📤", "withdrawal_account"), b("شحن الحساب 📥", "deposit_account")],
                 [b("🏠 القائمة الرئيسية", "menu")]]), h=True)

async def account_cmd(update: Update, ctx):
    u = await gate(update, ctx)
    if u: await hub(update, ctx, u)
    return END

# ---------------------------------------------------------------- الأزرار البسيطة
GUIDES = {
 "1": ("ما هو موقع Ichancy؟", "Ichancy منصة ترفيهية تقدم المراهنات الرياضية وألعاب السلوت والكازينو وألعاباً متنوعة، مع نظام آلي لاحتساب الأرباح بحسب النسب.\n\n"
       "الأقسام:\n• الرياضة: المراهنة على أحداث رياضية بنسب متغيرة.\n• السلوت: ألعاب حظ بآليات دوران بسيطة.\n• الكازينو: روليت وبلاك جاك وبوكر وغيرها.\n• الألعاب: ألعاب حظ ومهارة وتحديات سريعة.\n\nالموقع الرسمي: https://ichancy.com"),
 "2": ("كيفية شحن رصيد البوت", "1. اضغط «شحن رصيد» من القائمة.\n2. اختر طريقة الدفع.\n3. حوّل المبلغ إلى الرقم الظاهر (الحد الأدنى {min_dep:g}$).\n"
       "4. أدخل رقم عملية التحويل ثم المبلغ الذي أرسلته.\n5. راجع الملخص واضغط «تأكيد».\n✅ بعد مراجعة الإدارة يُضاف الرصيد إلى محفظتك وتصلك رسالة."),
 "3": ("كيفية إنشاء حساب Ichancy", "1. اضغط «حساب Ichancy» ثم «إنشاء حساب جديد».\n2. أدخل اسم المستخدم (إنجليزي وأرقام، 5 أحرف فأكثر).\n"
       "3. أدخل كلمة مرور لا تقل عن 8 أحرف.\n4. انتظر بضع ثوانٍ حتى تتم المعالجة.\n✅ يظهر لك اسم الدخول وكلمة السر ورقم اللاعب، وتجدها دائماً في «حساب Ichancy»."),
 "4": ("كيفية سحب الرصيد من البوت", "1. اضغط «سحب رصيد» من القائمة.\n2. اختر طريقة الاستلام.\n3. أدخل رقم حسابك المستلم بدقة.\n4. أدخل المبلغ بالدولار (الحد الأدنى {min_wd:g}$).\n"
       "5. راجع الملخص واضغط «تأكيد».\n✅ يُحجز المبلغ فوراً من محفظتك، ويُرسل إليك بعد مراجعة الإدارة. إن رُفض الطلب يعود المبلغ تلقائياً."),
 "5": ("كيفية شحن حساب Ichancy", "1. اضغط «حساب Ichancy» ثم «شحن الحساب».\n2. أدخل المبلغ المطلوب بالليرة السورية (NSP).\n3. يُخصم ما يعادله من محفظتك بالدولار.\n"
       "✅ يُضاف المبلغ إلى حسابك خلال ثوانٍ. الحد الأدنى {min_dep:g}$."),
 "6": ("كيفية سحب رصيد من حساب Ichancy", "1. اضغط «حساب Ichancy» ثم «سحب من الحساب».\n2. أدخل المبلغ المطلوب بالليرة السورية (NSP).\n"
       "✅ يُسحب المبلغ من حسابك ويُضاف ما يعادله بالدولار إلى محفظتك. الحد الأدنى {min_wd:g}$."),
}

async def simple_cb(update: Update, ctx):
    q = update.callback_query; await q.answer()
    u = await gate(update)
    if not u: return
    d = q.data
    if d == "menu": await say(update, welcome(u), menu_kb())
    elif d == "ichancy": await hub(update, ctx, u)
    elif d == "terms_and_conditions": await say(update, db.get("terms_text"), BACK)
    elif d == "guides":
        await say(update, "📝 الشروحات", M([[b(f"{v[0]}", f"guide_{k}")] for k, v in GUIDES.items()] + [[b("🏠 القائمة الرئيسية", "menu")]]))
    elif d.startswith("guide_"):
        t, body = GUIDES[d[6:]]
        await say(update, f"{t}\n\n" + body.format(min_dep=db.getf("min_deposit"), min_wd=db.getf("min_withdraw")),
                  M([[b("رجوع للشروحات", "guides")]]))
    elif d == "contact_us":
        await say(update, "✉️ الدعم", M([[b("مشكلة تقنية ضمن البوت", "problem_bot")], [b("مشكلة تقنية ضمن الموقع", "problem_site")],
                                         [b("🏠 القائمة الرئيسية", "menu")]]))
    elif d == "problem_bot":
        s = db.get("support_username")
        await say(update, f"للمشاكل التقنية في البوت تواصل مع الدعم: {s}" if s else "استخدم زر «رسالة للأدمن» لإرسال مشكلتك.", M([[b("رجوع", "contact_us")]]))
    elif d == "problem_site": await say(update, db.get("site_support_text"), M([[b("رجوع", "contact_us")]]))
    elif d == "log":
        rows = db.q("SELECT * FROM tx WHERE tg_id=? ORDER BY id DESC LIMIT 10", (u["tg_id"],))
        t = "\n".join(f"{r['created_at'][5:16]}  {db.KIND_AR.get(r['kind'], r['kind'])}  {r['usd']:+.2f}$" + (f" / {r['nsp']:,} NSP" if r['nsp'] else "") for r in rows)
        await say(update, "📜 آخر العمليات:\n\n" + (t or "لا توجد عمليات بعد."), BACK)
    elif d == "referral":
        me = (await ctx.bot.get_me()).username
        n = db.q("SELECT count(*) c FROM users WHERE referrer=?", (u["tg_id"],), one=True)["c"]
        e = db.q("SELECT coalesce(sum(usd),0) s FROM tx WHERE tg_id=? AND kind='referral'", (u["tg_id"],), one=True)["s"]
        act, need = ops.active_referrals(u["tg_id"]), int(db.getf("referral_min_active"))
        await say(update, f"💰 نظام الإحالات\n\nرابطك:\nhttps://t.me/{me}?start=ref_{u['tg_id']}\n\n"
                          f"النسبة: {db.getf('referral_percent'):g}% من كل إيداع يقوم به المُحال.\n"
                          f"تُحتسب الأرباح بعد {need} إحالات نشطة (قاموا بالتعبئة فعلاً).\n\n"
                          f"👥 المُحالون: {n}\n✅ النشطون: {act} من {need}\n💵 أرباحك: {e:.2f}$", BACK)

# ---------------------------------------------------------------- إنشاء حساب
S_USER, S_PASS = range(2)
async def create_entry(update: Update, ctx):
    await update.callback_query.answer()
    u = await gate(update)
    if not u: return END
    if u["game_login"]:
        await hub(update, ctx, u); return END
    pre = ""
    ch = db.get("required_channel")
    if ch:
        try:
            m = await ctx.bot.get_chat_member(ch, update.effective_user.id)
            ok = m.status in ("member", "administrator", "creator")
        except Exception: ok = False
        if not ok:
            await say(update, f"⚠️ يجب الاشتراك بالقناة أولاً: {ch}\nثم اضغط «إنشاء حساب» مجدداً.", BACK); return END
        pre = "✅ تم التحقق بنجاح!\n\n"
    await say(update, pre + "🔐 <b>إنشاء حساب Ichancy</b>\n\nأدخل اسم المستخدم الذي تريده.\n\n📌 الشروط:\n"
                           "• 5 أحرف أو أرقام على الأقل\n• حروف إنجليزية وأرقام فقط\n• بلا رموز خاصة أو أحرف عربية", BACK, h=True)
    return S_USER

async def got_username(update: Update, ctx):
    name = update.message.text.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{5,20}", name):
        await update.message.reply_text("❌ الاسم غير صالح: 5 إلى 20 حرفاً إنجليزياً أو أرقاماً فقط. حاول مجدداً:"); return S_USER
    ctx.user_data["login"] = name
    await update.message.reply_text("🔑 أدخل كلمة المرور (8 أحرف على الأقل، بلا مسافات):")
    return S_PASS

async def got_password(update: Update, ctx):
    pw, base = update.message.text.strip(), ctx.user_data.get("login")
    try: await update.message.delete()
    except Exception: pass
    if len(pw) < 8 or " " in pw:
        await say(update, "❌ كلمة المرور يجب ألا تقل عن 8 أحرف وبلا مسافات. أدخلها مجدداً:"); return S_PASS
    login, err = base, None
    for attempt in range(8):  # عند تكرار الاسم نضيف لاحقة عشوائية كما في البوت الأصلي
        ok, err = await asyncio.to_thread(api.register, login, pw)
        if ok: break
        login = base + "_" + "".join(random.choices(string.ascii_letters + string.digits, k=3))
    if not ok:
        await say(update, f"❌ فشل إنشاء الحساب: {err}\n\nأدخل اسم مستخدم آخر:"); return S_USER
    pid = await asyncio.to_thread(api.find_player_id, login)
    if not pid:
        await notify_admin(ctx, f"⚠️ حساب {login} أُنشئ لكن تعذر جلب player_id (المستخدم {update.effective_user.id})")
        await say(update, "تم إنشاء الحساب لكن تعذر ربطه تلقائياً. تواصل مع الدعم."); return END
    email = f"{login}@{api.domain}"
    db.set_account(update.effective_user.id, login, pid, email, ops.enc(pw))
    ctx.user_data.clear()
    await say(update, f"✅ <b>تم إنشاء الحساب بنجاح!</b>\n\n👤 الدخول: <code>{html.escape(login)}</code>\n🔒 كلمة السر: <code>{html.escape(pw)}</code>\n"
                      f"📧 الإيميل: <code>{html.escape(email)}</code>\n🆔 رقم اللاعب: <code>{pid}</code>\n🌐 https://www.ichancy.com/ar\n\n"
                      "تجد هذه البيانات دائماً في «حساب Ichancy».", M([[b("⚡️ حساب Ichancy", "ichancy")], [b("🏠 القائمة الرئيسية", "menu")]]), h=True)
    return END

# ---------------------------------------------------------------- محادثات بخطوة واحدة
FALLBACKS = [CommandHandler("start", start), CommandHandler("cancel", start), CallbackQueryHandler(simple_cb, pattern="^menu$")]
TXT = filters.TEXT & ~filters.COMMAND

def one_step(pattern, prompt, fn, numeric=True, need_account=True):
    async def entry(update, ctx):
        await update.callback_query.answer()
        u = await gate(update)
        if not u: return END
        if need_account and not u["game_login"]:
            await say(update, "أنشئ حساب Ichancy أولاً.", M([[b("إنشاء حساب جديد ➕", "create_account")], [b("🏠 القائمة الرئيسية", "menu")]])); return END
        await say(update, prompt, BACK); return 1
    async def recv(update, ctx):
        u = await gate(update)
        if not u: return END
        val = update.message.text.strip()
        if numeric:
            try: val = float(val.replace(",", ""))
            except ValueError:
                await update.message.reply_text("أدخل رقماً صحيحاً."); return 1
            if val <= 0:
                await update.message.reply_text("المبلغ يجب أن يكون أكبر من صفر."); return 1
        await say(update, await fn(ctx, u, val), welcome_kb(u))
        return END
    return CH(entry_points=[CallbackQueryHandler(entry, pattern=f"^{pattern}$")], states={1: [MessageHandler(TXT, recv)]},
              fallbacks=FALLBACKS, conversation_timeout=600)

def welcome_kb(u): return M([[b("⚡️ حساب Ichancy", "ichancy")], [b("🏠 القائمة الرئيسية", "menu")]])

async def do_deposit(ctx, u, nsp):
    nsp, rate = int(nsp), db.site_rate()
    if rate <= 0: return "⚠️ سعر الصرف غير مضبوط، تواصل مع الإدارة."
    usd = round(nsp / rate, 2)
    if usd < db.getf("min_deposit"): return f"❌ أقل مبلغ للشحن {db.getf('min_deposit'):g}$ (≈ {math.ceil(db.getf('min_deposit') * rate):,} NSP)"
    if not db.wallet_take(u["tg_id"], usd): return f"❌ رصيدك غير كافٍ. المطلوب {usd}$ ورصيدك {fresh(u)['wallet']:.2f}$"
    agent = await asyncio.to_thread(api.agent_balance)
    ok, err = (False, "رصيد الوكيل غير كافٍ") if (agent is not None and agent < nsp) else await asyncio.to_thread(api.deposit, u["player_id"], nsp)
    if not ok:
        db.wallet_add(u["tg_id"], usd)
        db.log(u["tg_id"], "deposit_game_failed", 0, nsp, "failed", err)
        await notify_admin(ctx, f"⚠️ فشل إيداع {nsp} NSP للمستخدم {u['tg_id']}: {err}")
        return "❌ فشلت العملية وأُعيد رصيدك كاملاً. حاول لاحقاً."
    db.log(u["tg_id"], "deposit_game", -usd, nsp)
    paid = ops.pay_referral(u, usd)
    if paid:
        try: await ctx.bot.send_message(paid[0], f"💰 حصلت على عمولة إحالة {paid[1]}$")
        except Exception: pass
    return f"✅ تمت العملية بنجاح: {nsp:,} NSP في حسابك (خُصم {usd}$)."

async def do_withdraw(ctx, u, nsp):
    nsp, rate = int(nsp), db.site_rate()
    if rate <= 0: return "⚠️ سعر الصرف غير مضبوط، تواصل مع الإدارة."
    if nsp / rate < db.getf("min_withdraw"): return f"❌ أقل مبلغ للسحب {db.getf('min_withdraw'):g}$ (≈ {math.ceil(db.getf('min_withdraw') * rate):,} NSP)"
    bal = await asyncio.to_thread(api.player_balance, u["player_id"])
    if bal is None: return "❌ تعذر الاتصال بالخدمة، حاول لاحقاً."
    if bal < nsp: return f"❌ رصيد حسابك {int(bal):,} NSP فقط."
    ok, err = await asyncio.to_thread(api.withdraw, u["player_id"], nsp)
    if not ok:
        await notify_admin(ctx, f"⚠️ فشل سحب {nsp} NSP للمستخدم {u['tg_id']}: {err}")
        return "❌ تعذر تنفيذ السحب. حاول لاحقاً."
    usd = round(nsp / rate, 2)
    db.wallet_add(u["tg_id"], usd); db.log(u["tg_id"], "withdraw_game", usd, -nsp)
    return f"✅ تم سحب {nsp:,} NSP وإضافة {usd}$ إلى محفظتك."

async def do_gift_redeem(ctx, u, code):
    amt = db.redeem_gift(code, u["tg_id"])
    return f"🎉 تمت إضافة {amt:.2f}$ إلى محفظتك." if amt else "❌ الكود غير صحيح، أو مستخدم، أو ليس مخصصاً لحسابك."

# ---------------------------------------------------------------- شحن المحفظة (يدوي بموافقة الأدمن)
T_METHOD, T_REF, T_AMT, T_OK = range(10, 14)
def req_text(rid):
    r = db.q("SELECT r.*, u.game_login, u.tg_username FROM requests r LEFT JOIN users u USING(tg_id) WHERE r.id=?", (rid,), one=True)
    name, cur, _ = METHODS[r["method"]]
    lines = [f"🆕 طلب {'شحن' if r['kind'] == 'topup' else 'سحب'} #{rid}", f"👤 العضو: {r['tg_id']} @{r['tg_username'] or '—'} ({r['game_login'] or '—'})",
             f"📌 الطريقة: {name}", f"💰 المبلغ: {r['amount']:,.0f} {cur} (≈ {r['usd']}$)",
             f"{'🔢 رقم العملية' if r['kind'] == 'topup' else '📲 الحساب المستلم'}: {r['ref']}", f"📅 {r['created_at']}"]
    return "\n".join(lines)

async def send_request_to_admin(ctx, rid):
    await notify_admin(ctx, req_text(rid), M([[b("✅ تأكيد", f"approve_{rid}"), b("❌ رفض", f"reject_{rid}")]]))

async def tp_start(update: Update, ctx):
    await update.callback_query.answer()
    if not await gate(update): return END
    if not any(db.get(v[2]) for v in METHODS.values()):
        await say(update, "الشحن غير متاح حالياً. تواصل مع الدعم.", BACK); return END
    await say(update, "📥 شحن رصيد\n\nاختر طريقة الدفع:", methods_kb("tp", True)); return T_METHOD

async def tp_method(update: Update, ctx):
    q = update.callback_query; await q.answer()
    k = q.data.split("_")[1]; name, cur, key = METHODS[k]
    addr = db.get(key)
    if not addr:
        await say(update, "هذه الطريقة غير متاحة حالياً.", BACK); return END
    ctx.user_data["tp"] = k
    mn, rate = db.getf("min_deposit"), db.getf("exchange_rate")
    lim = f"{mn:g}$" + (f" (≈ {math.ceil(mn * rate):,} SYP)" if cur == "SYP" else "")
    await say(update, f"{name}\n\nأرسل المبلغ إلى:\n<code>{html.escape(addr)}</code>\n\nأقل قيمة للشحن {lim}. أي قيمة أقل لا يمكن شحنها أو استرجاعها.\n\n"
                      "ثم أدخل <b>رقم عملية التحويل</b> 👇", BACK, h=True)
    return T_REF

async def tp_ref(update: Update, ctx):
    ref = update.message.text.strip()[:64]
    if db.q("SELECT 1 FROM requests WHERE kind='topup' AND ref=? AND status!='rejected'", (ref,), one=True):
        await update.message.reply_text("❌ رقم العملية مستخدم سابقاً. تحقق منه وأعد إدخاله:"); return T_REF
    ctx.user_data["tp_ref"] = ref
    cur = METHODS[ctx.user_data["tp"]][1]
    await update.message.reply_text(f"أدخل المبلغ الذي أرسلته ({'بالليرة السورية' if cur == 'SYP' else 'بالدولار'}):"); return T_AMT

async def tp_amount(update: Update, ctx):
    k = ctx.user_data["tp"]; name, cur, _ = METHODS[k]
    try: amt = float(update.message.text.replace(",", "").strip())
    except ValueError:
        await update.message.reply_text("أدخل رقماً صحيحاً."); return T_AMT
    rate = db.getf("exchange_rate")
    usd = round(amt if cur == "USD" else amt / rate, 2) if rate > 0 else 0
    if usd < db.getf("min_deposit"):
        await update.message.reply_text(f"❌ أقل قيمة للشحن {db.getf('min_deposit'):g}$. أدخل مبلغاً أكبر:"); return T_AMT
    ctx.user_data.update(tp_amt=amt, tp_usd=usd)
    await update.message.reply_text(f"📋 ملخص الطلب\n\n{name}\nرقم العملية: {ctx.user_data['tp_ref']}\nالمبلغ: {amt:,.0f} {cur}\nيعادل: {usd}$",
                                    reply_markup=M([[b("تأكيد ✅", "tp_ok"), b("إلغاء", "tp_no")]]))
    return T_OK

async def tp_confirm(update: Update, ctx):
    q = update.callback_query; await q.answer()
    u = await gate(update)
    if not u: return END
    if q.data == "tp_no":
        ctx.user_data.clear(); await say(update, "تم إلغاء الطلب.", BACK); return END
    d = ctx.user_data
    if "tp_ref" not in d or "tp_usd" not in d:
        await say(update, "انتهت صلاحية الطلب. ابدأ من جديد.", BACK); return END
    if db.q("SELECT 1 FROM requests WHERE kind='topup' AND ref=? AND status!='rejected'", (d["tp_ref"],), one=True):
        await say(update, "❌ رقم العملية مستخدم سابقاً.", BACK); return END
    rid = db.x("INSERT INTO requests(tg_id,kind,method,amount,usd,ref) VALUES(?,?,?,?,?,?)", (u["tg_id"], "topup", d["tp"], d["tp_amt"], d["tp_usd"], d["tp_ref"]))[1]
    await send_request_to_admin(ctx, rid)
    d.clear()
    await say(update, f"✅ تم إرسال طلبك #{rid} للمراجعة. سيتم إشعارك عند الموافقة أو الرفض.", BACK); return END

# ---------------------------------------------------------------- سحب الرصيد (يدوي بموافقة الأدمن)
P_METHOD, P_DEST, P_AMT, P_OK = range(20, 24)
async def po_start(update: Update, ctx):
    await update.callback_query.answer()
    if not await gate(update): return END
    await say(update, "📤 سحب رصيد\n\nاختر طريقة الاستلام:", methods_kb("po")); return P_METHOD

async def po_method(update: Update, ctx):
    q = update.callback_query; await q.answer()
    k = q.data.split("_")[1]; ctx.user_data["po"] = k
    hint = {"syr": "رقم سيريتل كاش الذي تريد استلام أرباحك عليه", "shs": "معرّف حساب شام كاش المستلم", "shu": "معرّف حساب شام كاش المستلم"}[k]
    await say(update, f"{METHODS[k][0]}\n\nأرسل {hint}:", BACK); return P_DEST

async def po_dest(update: Update, ctx):
    ctx.user_data["po_dest"] = update.message.text.strip()[:64]
    u = db.get_user(update.effective_user.id)
    await update.message.reply_text(f"💼 رصيد محفظتك: {u['wallet']:.2f}$\nأدخل المبلغ المراد سحبه بالدولار (الحد الأدنى {db.getf('min_withdraw'):g}$):"); return P_AMT

async def po_amount(update: Update, ctx):
    u = db.get_user(update.effective_user.id); k = ctx.user_data["po"]; name, cur, _ = METHODS[k]
    try: usd = round(float(update.message.text.replace(",", "").strip()), 2)
    except ValueError:
        await update.message.reply_text("أدخل رقماً صحيحاً."); return P_AMT
    if usd < db.getf("min_withdraw"):
        await update.message.reply_text(f"❌ أقل مبلغ للسحب {db.getf('min_withdraw'):g}$."); return P_AMT
    if usd > u["wallet"]:
        await update.message.reply_text(f"❌ رصيدك {u['wallet']:.2f}$ فقط."); return P_AMT
    amt = usd if cur == "USD" else round(usd * db.getf("exchange_rate"))
    ctx.user_data.update(po_usd=usd, po_amt=amt)
    await update.message.reply_text(f"📋 ملخص السحب\n\n{name}\nالحساب المستلم: {ctx.user_data['po_dest']}\nالمبلغ: {usd}$\nستستلم ≈ {amt:,.0f} {cur}",
                                    reply_markup=M([[b("تأكيد ✅", "po_ok"), b("إلغاء", "po_no")]])); return P_OK

async def po_confirm(update: Update, ctx):
    q = update.callback_query; await q.answer()
    u = await gate(update)
    if not u: return END
    d = ctx.user_data
    if q.data == "po_no":
        d.clear(); await say(update, "تم إلغاء الطلب.", BACK); return END
    if "po_usd" not in d or "po_dest" not in d:
        await say(update, "انتهت صلاحية الطلب. ابدأ من جديد.", BACK); return END
    if not db.wallet_take(u["tg_id"], d["po_usd"]):
        await say(update, "❌ رصيدك غير كافٍ.", BACK); return END
    rid = db.x("INSERT INTO requests(tg_id,kind,method,amount,usd,ref) VALUES(?,?,?,?,?,?)", (u["tg_id"], "payout", d["po"], d["po_amt"], d["po_usd"], d["po_dest"]))[1]
    db.log(u["tg_id"], "payout", -d["po_usd"], 0, "pending", f"#{rid}")
    await send_request_to_admin(ctx, rid)
    usd = d["po_usd"]; d.clear()
    await say(update, f"✅ تم استلام طلب السحب #{rid} وحُجز {usd}$ من محفظتك.\nتتم المعالجة خلال مدة أقصاها نصف ساعة.", BACK); return END

# ---------------------------------------------------------------- قبول/رفض الأدمن من تيليغرام
async def admin_decide(update: Update, ctx):
    q = update.callback_query
    if update.effective_user.id != ADMIN_ID:
        await q.answer("غير مصرّح لك.", show_alert=True); return
    action, rid = q.data.split("_"); await q.answer()
    st, r = ops.decide(int(rid), action)
    if st == "missing": await q.edit_message_text("❌ الطلب غير موجود."); return
    if st == "already": await q.edit_message_reply_markup(None); await q.message.reply_text(f"سبق البتّ في الطلب #{rid}."); return
    await q.edit_message_text(q.message.text + ("\n\n✅ تمت الموافقة" if action == "approve" else "\n\n❌ تم الرفض"))
    try: await ctx.bot.send_message(r["tg_id"], ops.user_message(r, action))
    except Exception as e: log.warning("notify user: %s", e)

# ---------------------------------------------------------------- إهداء الرصيد
G_TO, G_AMT = range(30, 32)
async def gift_start(update: Update, ctx):
    await update.callback_query.answer()
    u = await gate(update)
    if not u: return END
    n = db.q("SELECT count(*) FROM tx WHERE tg_id=? AND kind='gift_send' AND date(created_at)=date('now','localtime')", (u["tg_id"],), one=True)[0] + 1
    await say(update, f"🎁 إهداء رصيد\n\nهذه العملية رقم {n} لليوم، وتُقتطع عمولة {db.getf('gift_fee_percent'):g}% من المبلغ المرسل.\n\n"
                      f"معرّفك: {u['tg_id']}\nأرسل معرّف تيليغرام (رقم) للشخص الذي تريد إهداءه.\nيجد المستخدم معرّفه بالأمر /balance", BACK)
    return G_TO

async def gift_to(update: Update, ctx):
    t = update.message.text.strip()
    if not t.isdigit() or int(t) == update.effective_user.id:
        await update.message.reply_text("❌ أدخل معرّفاً رقمياً صحيحاً لشخص آخر."); return G_TO
    if fresh(db.get_user(update.effective_user.id))["wallet"] <= 0:
        await say(update, "ليس لديك رصيد للإهداء.", BACK); return END
    ctx.user_data["gift_to"] = int(t)
    await update.message.reply_text("أدخل المبلغ المراد إهداؤه بالدولار:"); return G_AMT

async def gift_amount(update: Update, ctx):
    u = db.get_user(update.effective_user.id)
    try: amt = round(float(update.message.text.replace(",", "").strip()), 2)
    except ValueError: amt = 0
    if amt <= 0:
        await update.message.reply_text("أدخل مبلغاً صحيحاً."); return G_AMT
    if not db.wallet_take(u["tg_id"], amt):
        await say(update, "❌ ليس معك رصيد كافٍ. يرجى تعبئة الرصيد.", BACK); return END
    fee = round(amt * db.getf("gift_fee_percent") / 100, 2)
    code = db.create_gift(round(amt - fee, 2), u["tg_id"], ctx.user_data["gift_to"])
    db.log(u["tg_id"], "gift_send", -amt, note=f"إلى {ctx.user_data['gift_to']}")
    ctx.user_data.clear()
    await say(update, f"✅ تمت العملية بنجاح!\n\nكود الهدية:\n<code>{code}</code>\n\nيستطيع المستلم وحده استخدامه من «كود هدية».", BACK, h=True)
    return END

# ---------------------------------------------------------------- رسالة للأدمن (نص أو صورة)
MSG = 40
async def msg_start(update: Update, ctx):
    await update.callback_query.answer()
    if not await gate(update): return END
    await say(update, "📨 اكتب رسالتك للإدارة، أو أرسل صورة (مع تعليق إن أردت):", BACK); return MSG

async def msg_recv(update: Update, ctx):
    u = await gate(update)
    if not u: return END
    m = update.message
    if m.photo:
        text = "📷 صورة" + (f": {m.caption}" if m.caption else "")
        mid = db.x("INSERT INTO messages(tg_id,text) VALUES(?,?)", (u["tg_id"], text[:2000]))[1]
        try: await ctx.bot.send_photo(ADMIN_CHAT, m.photo[-1].file_id, caption=f"📨 رسالة #{mid} من {u['tg_id']} (@{u['tg_username']})\n{m.caption or ''}"[:1000])
        except Exception as e: log.warning("send_photo: %s", e)
    else:
        mid = db.x("INSERT INTO messages(tg_id,text) VALUES(?,?)", (u["tg_id"], m.text[:2000]))[1]
        await notify_admin(ctx, f"📨 رسالة #{mid} من {u['tg_id']} (@{u['tg_username']}):\n{m.text[:800]}")
    await say(update, "✅ وصلت رسالتك للإدارة وسنرد عليك هنا.", BACK); return END

# ---------------------------------------------------------------- الأخطاء + التجميع
async def on_error(update, ctx):
    log.error("خطأ غير متوقع", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_chat:
        try: await update.effective_chat.send_message("⚠️ حدث خطأ غير متوقع. حاول مرة أخرى، وإن تكرر تواصل مع الدعم.")
        except Exception: pass

def build() -> Application:
    app = Application.builder().token(os.environ["BOT_TOKEN"]).post_init(_post_init).build()
    conv = lambda entry, states, t=900: CH(entry_points=[entry], states=states, fallbacks=FALLBACKS, conversation_timeout=t)
    cq = CallbackQueryHandler
    app.add_handler(conv(cq(create_entry, pattern="^create_account$"), {S_USER: [MessageHandler(TXT, got_username)], S_PASS: [MessageHandler(TXT, got_password)]}, 600))
    app.add_handler(conv(cq(tp_start, pattern="^deposit$"), {T_METHOD: [cq(tp_method, pattern="^tp_")], T_REF: [MessageHandler(TXT, tp_ref)],
                                                              T_AMT: [MessageHandler(TXT, tp_amount)], T_OK: [cq(tp_confirm, pattern="^tp_(ok|no)$")]}))
    app.add_handler(conv(cq(po_start, pattern="^withdrawal$"), {P_METHOD: [cq(po_method, pattern="^po_")], P_DEST: [MessageHandler(TXT, po_dest)],
                                                                 P_AMT: [MessageHandler(TXT, po_amount)], P_OK: [cq(po_confirm, pattern="^po_(ok|no)$")]}))
    app.add_handler(conv(cq(gift_start, pattern="^send_gift$"), {G_TO: [MessageHandler(TXT, gift_to)], G_AMT: [MessageHandler(TXT, gift_amount)]}))
    app.add_handler(conv(cq(msg_start, pattern="^admin_message$"), {MSG: [MessageHandler((TXT | filters.PHOTO), msg_recv)]}))
    app.add_handler(one_step("deposit_account", "📥 أدخل المبلغ بالليرة السورية (NSP) المراد تحويله إلى حسابك:", do_deposit))
    app.add_handler(one_step("withdrawal_account", "📤 أدخل المبلغ بالليرة السورية (NSP) المراد سحبه من حسابك:", do_withdraw))
    app.add_handler(one_step("reseive_gift", "🔑 أدخل كود الهدية:", do_gift_redeem, numeric=False, need_account=False))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("account", account_cmd))
    app.add_handler(cq(admin_decide, pattern=r"^(approve|reject)_\d+$"))
    app.add_handler(cq(simple_cb))
    app.add_error_handler(on_error)
    return app

async def _post_init(app):
    await app.bot.set_my_commands([BotCommand("start", "البدء"), BotCommand("balance", "رصيدي"), BotCommand("account", "حساب Ichancy")])
