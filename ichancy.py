"""عميل Ichancy. بدون ICHANCY_COOKIE يعمل بوضع تجريبي (Mock) للاختبار."""
import os, random, logging, requests
import db
log = logging.getLogger("ichancy")
BASE = "https://agents.ichancy.com/global/api/"

class Ichancy:
    def __init__(self):
        self.domain = os.getenv("EMAIL_DOMAIN", "example.com")
        self._m = {}  # لاعبون وهميون (الوضع التجريبي)

    # الكوكيز و PARENT_ID: من الداشبورد أولاً ثم من .env — تتغير دون إعادة تشغيل
    def _cookie(self): return (db.get("ichancy_cookie") or os.getenv("ICHANCY_COOKIE", "")).strip()
    @property
    def parent(self): return (db.get("parent_id") or os.getenv("PARENT_ID", "")).strip()
    @property
    def mock(self): return os.getenv("ICHANCY_MOCK") == "1" or not self._cookie()

    def _headers(self):
        return {"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0"), "Cookie": self._cookie(),
                "Accept": "application/json, text/plain, */*", "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://agents.ichancy.com", "Referer": "https://agents.ichancy.com/dashboard"}

    def keepalive(self):
        """طلبات خفيفة تُبقي الجلسة حيّة (كما في infinit_browsing الأصلي). تعيد (ok, رسالة)."""
        if self.mock: return True, "mock"
        try:
            self._post("core/getData", {}); self._post("Agent/getAgentWallet", {}); return True, "ok"
        except Exception as e:
            return False, str(e)

    def _post(self, path, payload):
        r = requests.post(BASE + path, json=payload, headers=self._headers(), timeout=30)
        if r.headers.get("cf-mitigated") == "challenge":
            raise RuntimeError("انتهت صلاحية الكوكيز (Cloudflare). جدّدها من الداشبورد ← الإعدادات")
        r.raise_for_status()
        j = r.json()   # صفحة HTML بدل JSON تعني غالباً أن الجلسة انتهت
        log.info("%s -> %s", path, str(j)[:300])
        return j

    @staticmethod
    def _err(j):
        try: return j["notification"][0]["content"]
        except Exception: return "رفض الخادم العملية"

    def register(self, login, password):
        if self.mock:
            if login.lower() in self._m: return False, "اسم المستخدم مستخدم مسبقاً"
            self._m[login.lower()] = {"id": str(random.randint(10**8, 10**9)), "bal": 0}
            return True, None
        try:
            j = self._post("Player/registerPlayer", {"player": {
                "login": login, "email": f"{login}@{self.domain}", "password": password, "parentId": self.parent}})
            return (True, None) if j.get("result") else (False, self._err(j))
        except Exception as e:
            return False, str(e)

    def find_player_id(self, login):
        if self.mock:
            p = self._m.get(login.lower()); return p["id"] if p else None
        try:
            for start in range(0, 500, 100):
                j = self._post("Statistics/getPlayersStatisticsPro", {"start": start, "limit": 100, "filter": {}})
                recs = (j.get("result") or {}).get("records") or []
                for r in recs:
                    if str(r.get("username", "")).lower() == login.lower(): return str(r["playerId"])
                if len(recs) < 100: break
        except Exception as e:
            log.error("find_player_id: %s", e)
        return None

    def _mock_by_id(self, pid):
        return next((p for p in self._m.values() if p["id"] == str(pid)), None)

    def player_balance(self, pid):
        if self.mock:
            p = self._mock_by_id(pid); return p["bal"] if p else None
        try:
            return float(self._post("Player/getPlayerBalanceById", {"playerId": pid})["result"][0]["balance"])
        except Exception as e:
            log.error("player_balance: %s", e); return None

    def agent_balance(self):
        if self.mock: return 10**9
        try:
            return float(self._post("Agent/getAgentWalletByAgentId",
                                    {"affiliateId": self.parent, "currencyCode": "NSP"})["result"]["balance"])
        except Exception as e:
            log.error("agent_balance: %s", e); return None

    def _move(self, path, pid, amount):
        try:
            j = self._post(path, {"amount": amount, "comment": None, "playerId": pid,
                                  "currencyCode": "NSP", "moneyStatus": 5})
            return (True, None) if j.get("result") not in (None, False) else (False, self._err(j))
        except Exception as e:
            return False, str(e)

    def deposit(self, pid, amount):
        if self.mock:
            p = self._mock_by_id(pid)
            if not p: return False, "لاعب غير موجود"
            p["bal"] += amount; return True, None
        return self._move("Player/depositToPlayer", pid, amount)

    def withdraw(self, pid, amount):
        if self.mock:
            p = self._mock_by_id(pid)
            if not p or p["bal"] < amount: return False, "رصيد غير كاف"
            p["bal"] -= amount; return True, None
        return self._move("Player/withdrawFromPlayer", pid, -amount)
