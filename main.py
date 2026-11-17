import os, time, logging, threading
from dotenv import load_dotenv
load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # لا نطبع التوكن في السجلات

import requests, dashboard, bot

def keepalive_loop():
    """كل 4 دقائق نُبقي جلسة الكاشير حيّة، وننبّه الأدمن (مرة كل ساعة) إن انقطعت."""
    last_alert = 0
    while True:
        time.sleep(240)
        ok, msg = bot.api.keepalive()
        if ok: continue
        logging.warning("keepalive failed: %s", msg)
        if time.time() - last_alert > 3600 and bot.ADMIN_ID:
            last_alert = time.time()
            try:
                requests.post(f"https://api.telegram.org/bot{os.environ['BOT_TOKEN']}/sendMessage", timeout=15, json={
                    "chat_id": bot.ADMIN_ID, "text": "⚠️ انقطع اتصال البوت بحساب الكاشير في Ichancy (غالباً انتهت الكوكيز). "
                                                     "الصقوا كوكيز جديدة من الداشبورد ← الإعدادات."})
            except Exception: pass

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    threading.Thread(target=lambda: dashboard.app.run(host="0.0.0.0", port=port, threaded=True), daemon=True).start()
    threading.Thread(target=keepalive_loop, daemon=True).start()
    logging.info("Dashboard on :%s | Ichancy mock=%s", port, bot.api.mock)
    bot.build().run_polling(drop_pending_updates=True)
