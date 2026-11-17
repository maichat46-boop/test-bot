"""فحص الاتصال بحساب الكاشير: يطبع نتيجة الطلبات (دون طباعة الكوكيز) لمعرفة PARENT_ID والتأكد أن الجلسة تعمل.
التشغيل:  python check_ichancy.py     (بعد وضع الكوكيز في .env أو في الداشبورد)"""
import json
from dotenv import load_dotenv
load_dotenv(override=True)
import db
from ichancy import Ichancy

api = Ichancy()
print("وضع تجريبي (Mock):", api.mock)
if api.mock:
    raise SystemExit("لا توجد كوكيز. ضعها في ICHANCY_COOKIE داخل .env ثم أعد التشغيل.")
print("PARENT_ID الحالي:", api.parent or "(غير مضبوط)")
for path in ("core/getData", "Agent/getAgentWallet"):
    try:
        j = api._post(path, {})
        txt = json.dumps(j, ensure_ascii=False)
        print(f"\n== {path}: ناجح\n{txt[:1500]}{'...' if len(txt) > 1500 else ''}")
    except Exception as e:
        print(f"\n== {path}: فشل -> {e}")
print("\nابحث في المخرجات عن رقم المعرّف (id / affiliateId) الخاص بالكاشير وضعه في PARENT_ID.")
print("الرصيد عبر الدالة:", api.agent_balance())
