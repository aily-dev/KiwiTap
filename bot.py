import os, json, time, hmac, hashlib, sqlite3, threading
from urllib.parse import parse_qsl
import telebot
from telebot import types
from flask import Flask, request, jsonify, send_from_directory, abort, g, make_response

TOKEN = os.getenv("BOT_TOKEN", "8977586981:AAGSgdQt1Dujh9lemR8-lddf-RUojTHdOOg")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://57c0-91-107-184-61.ngrok-free.app").rstrip("/")
DEV = os.getenv("DEV") == "1"
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "7558568682").replace(" ", "").split(",") if x}
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
BASE = os.path.dirname(os.path.abspath(__file__))
WELCOME_PHOTO = os.path.join(BASE, "assets", "1405-08-14 11.50.23.jpg")
TASK_WAIT = 8

DEFAULTS = dict(ref_bonus=5000, ref_premium_bonus=15000, base_energy=1000, offline_cap_hours=3,
                daily_base=500, frenzy_sec=20, frenzy_mult=5, max_boosts=3, tap_rate=25, maintenance=0,
                welcome_text=("🥝 Welcome to KiwiTap, {name}!\n\n"
                              "👆 Tap the kiwi and collect points\n"
                              "🌳 Build your farm — it earns while you sleep\n"
                              "🎡 Spin the lucky wheel every day\n"
                              "🏆 Climb the weekly leaderboard\n"
                              "👥 Invite friends: +1000 points for both\n\n"
                              "🪂 Airdrop plans are on the way — details soon!"))
LEAGUES = [("Sprout", 0), ("Bronze", 6_000), ("Silver", 50_000), ("Gold", 250_000), ("Diamond", 1_000_000)]

db = sqlite3.connect(os.path.join(BASE, "game.db"), check_same_thread=False)
db.row_factory = sqlite3.Row
lock = threading.Lock()

def q(sql, args=(), one=False):
    with lock:
        cur = db.execute(sql, args); db.commit(); rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows

q("""CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, name TEXT, coins REAL DEFAULT 0, energy REAL DEFAULT 1000, ts REAL,
    tap_lvl INTEGER DEFAULT 1, energy_lvl INTEGER DEFAULT 1, regen_lvl INTEGER DEFAULT 1,
    streak INTEGER DEFAULT 0, last_daily TEXT DEFAULT '', referrer INTEGER, ref_count INTEGER DEFAULT 0)""")
for col in ("refill_used INTEGER DEFAULT 0", "frenzy_used INTEGER DEFAULT 0", "boost_day TEXT DEFAULT ''",
            "frenzy_until REAL DEFAULT 0", "banned INTEGER DEFAULT 0", "created REAL DEFAULT 0", "last_seen REAL DEFAULT 0"):
    try: q(f"ALTER TABLE users ADD COLUMN {col}")
    except sqlite3.OperationalError: pass
q("CREATE TABLE IF NOT EXISTS cards(uid INTEGER, card TEXT, lvl INTEGER, PRIMARY KEY(uid, card))")
q("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
q("""CREATE TABLE IF NOT EXISTS card_defs(id TEXT PRIMARY KEY, name TEXT, icon TEXT, base_cost INTEGER,
    base_profit INTEGER, enabled INTEGER DEFAULT 1)""")
q("""CREATE TABLE IF NOT EXISTS task_defs(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, reward INTEGER,
    kind TEXT DEFAULT 'link', need INTEGER DEFAULT 0, url TEXT DEFAULT '', enabled INTEGER DEFAULT 1)""")
q("CREATE TABLE IF NOT EXISTS task_prog(uid INTEGER, task INTEGER, started REAL DEFAULT 0, done INTEGER DEFAULT 0, PRIMARY KEY(uid, task))")
q("CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, reward INTEGER, max_uses INTEGER DEFAULT 0, uses INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1)")
q("CREATE TABLE IF NOT EXISTS promo_used(uid INTEGER, code TEXT, PRIMARY KEY(uid, code))")

if not q("SELECT 1 FROM card_defs", one=True):
    for r in [("miner", "Home miner", "pickaxe", 1000, 80), ("farm", "Server farm", "server", 5000, 450),
              ("ads", "Ad network", "megaphone", 20000, 2000), ("bank", "Exchange", "landmark", 80000, 9000),
              ("labs", "AI lab", "brain", 300000, 40000)]:
        q("INSERT INTO card_defs VALUES(?,?,?,?,?,1)", r)
if not q("SELECT 1 FROM task_defs", one=True):
    q("INSERT INTO task_defs(title,reward,kind,need) VALUES('Invite 3 friends',25000,'invite',3)")
    q("INSERT INTO task_defs(title,reward,kind,need) VALUES('Invite 10 friends',100000,'invite',10)")

def cfg(k):
    r = q("SELECT v FROM settings WHERE k=?", (k,), one=True)
    v = str(r["v"]) if r else str(DEFAULTS[k])
    try: return float(v) if "." in v else int(v)
    except ValueError: return v

card_cost = lambda d, lvl: int(d["base_cost"] * 1.8 ** lvl)
tap_cost = lambda lvl: 500 * 2 ** (lvl - 1)
energy_cost = lambda lvl: 400 * 2 ** (lvl - 1)
regen_cost = lambda lvl: 600 * 2 ** (lvl - 1)
max_energy = lambda u: int(cfg("base_energy")) + 500 * (u["energy_lvl"] - 1)
card_defs = lambda: {r["id"]: dict(r) for r in q("SELECT * FROM card_defs WHERE enabled=1")}
card_levels = lambda uid: {r["card"]: r["lvl"] for r in q("SELECT card,lvl FROM cards WHERE uid=?", (uid,))}

def profit_hour(uid):
    d = card_defs()
    return sum(d[c]["base_profit"] * l for c, l in card_levels(uid).items() if c in d)

def get_user(uid, name="Player"):
    u = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not u:
        q("INSERT INTO users(id,name,ts,created,energy) VALUES(?,?,?,?,?)", (uid, name, time.time(), time.time(), cfg("base_energy")))
        u = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    return u

def sync(uid):
    u = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    now = time.time(); dt = max(0, now - u["ts"]); today = time.strftime("%Y-%m-%d")
    if u["boost_day"] != today:
        q("UPDATE users SET boost_day=?, refill_used=0, frenzy_used=0 WHERE id=?", (today, uid))
    energy = min(max_energy(u), u["energy"] + dt * u["regen_lvl"])
    coins = u["coins"] + min(dt, cfg("offline_cap_hours") * 3600) * profit_hour(uid) / 3600
    q("UPDATE users SET energy=?, coins=?, ts=?, last_seen=? WHERE id=?", (energy, coins, now, now, uid))
    return dt

def state(uid):
    u = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    lv, defs, now = card_levels(uid), card_defs(), time.time()
    prog = {r["task"]: r for r in q("SELECT * FROM task_prog WHERE uid=?", (uid,))}
    today = time.strftime("%Y-%m-%d")
    yest = time.strftime("%Y-%m-%d", time.localtime(now - 86400))
    streak = u["streak"] if u["last_daily"] in (today, yest) else 0
    coins = int(u["coins"])
    li = max((i for i, (_, t) in enumerate(LEAGUES) if coins >= t), default=0)
    tasks = []
    for t in q("SELECT * FROM task_defs WHERE enabled=1 ORDER BY id"):
        p = prog.get(t["id"]); done = bool(p and p["done"])
        wait = max(0, TASK_WAIT - (now - p["started"])) if (t["kind"] == "link" and p and p["started"] and not done) else None
        tasks.append(dict(id=t["id"], title=t["title"], reward=t["reward"], kind=t["kind"], url=t["url"], need=t["need"],
                          done=done, started=bool(p and p["started"]), wait=wait, progress=min(u["ref_count"], t["need"])))
    return dict(
        coins=u["coins"], energy=u["energy"], max_energy=max_energy(u), power=u["tap_lvl"],
        regen=u["regen_lvl"], profit_hour=profit_hour(uid),
        tap_lvl=u["tap_lvl"], energy_lvl=u["energy_lvl"], regen_lvl=u["regen_lvl"],
        tap_cost=tap_cost(u["tap_lvl"]), energy_cost=energy_cost(u["energy_lvl"]), regen_cost=regen_cost(u["regen_lvl"]),
        cards=[dict(id=c, name=d["name"], icon=d["icon"], lvl=lv.get(c, 0), cost=card_cost(d, lv.get(c, 0)),
                    profit=d["base_profit"]) for c, d in defs.items()],
        daily_ready=u["last_daily"] != today, streak=streak, daily_reward=int(cfg("daily_base")) * min(streak + 1, 10),
        tasks=tasks, ref_count=u["ref_count"], ref_link=f"https://t.me/{BOT_USERNAME}?start=ref_{uid}",
        ref_bonus=cfg("ref_bonus"), league=LEAGUES[li][0], league_from=LEAGUES[li][1],
        league_to=LEAGUES[li + 1][1] if li + 1 < len(LEAGUES) else None,
        league_next=LEAGUES[li + 1][0] if li + 1 < len(LEAGUES) else None,
        rank=q("SELECT COUNT(*)+1 AS r FROM users WHERE coins > ?", (u["coins"],), one=True)["r"],
        total=q("SELECT COUNT(*) AS c FROM users", one=True)["c"],
        has_upgrade=bool(u["tap_lvl"] > 1 or u["energy_lvl"] > 1 or u["regen_lvl"] > 1 or lv),
        max_boosts=cfg("max_boosts"), refill_left=cfg("max_boosts") - u["refill_used"],
        frenzy_left=cfg("max_boosts") - u["frenzy_used"], frenzy_mult=cfg("frenzy_mult"),
        frenzy_sec=max(0, u["frenzy_until"] - now))


def check_init(init_data):
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True)); got = data.pop("hash")
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest(), got): return None
        if time.time() - int(data["auth_date"]) > 86400: return None
        return json.loads(data["user"])
    except Exception:
        return None

def err(msg, code=400): abort(make_response(jsonify(error=msg), code))

def auth():
    init = request.headers.get("X-Init-Data", "")
    user = dict(id=1, first_name="Dev") if (DEV and not init) else (check_init(init) or abort(401))
    u = get_user(user["id"], user.get("first_name", "Player"))
    if u["banned"]: err("Your account is banned", 403)
    if cfg("maintenance") and user["id"] not in ADMIN_IDS: err("Under maintenance, please come back soon", 503)
    g.dt = sync(user["id"])
    return user["id"]

def admin():
    if ADMIN_KEY and hmac.compare_digest(request.headers.get("X-Admin-Key", ""), ADMIN_KEY): return True
    u = check_init(request.headers.get("X-Init-Data", ""))
    if u and u["id"] in ADMIN_IDS: return True
    abort(401)


app = Flask(__name__)

def page(name):
    for folder in ("templates", "static", "."):
        if os.path.exists(os.path.join(BASE, folder, name)):
            return send_from_directory(os.path.join(BASE, folder), name)
    abort(404)

@app.get("/")
def index(): return page("index.html")

@app.get("/admin")
def admin_page(): return page("admin.html")

@app.post("/api/state")
def api_state(): return jsonify(state(auth()))

@app.post("/api/tap")
def api_tap():
    uid = auth(); taps = int(request.json.get("taps", 0))
    u = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    n = max(0, min(taps, int(u["energy"]), int(cfg("tap_rate") * max(g.dt, 1)) + 10))
    mult = cfg("frenzy_mult") if time.time() < u["frenzy_until"] else 1
    q("UPDATE users SET coins=coins+?, energy=energy-? WHERE id=?", (n * u["tap_lvl"] * mult, n, uid))
    return jsonify(state(uid))

@app.post("/api/upgrade")
def api_upgrade():
    uid = auth(); kind = request.json.get("type")
    u = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    col = {"tap": ("tap_lvl", tap_cost), "energy": ("energy_lvl", energy_cost), "regen": ("regen_lvl", regen_cost)}.get(kind)
    if not col: abort(400)
    cost = col[1](u[col[0]])
    if u["coins"] < cost: err("Not enough points")
    q(f"UPDATE users SET coins=coins-?, {col[0]}={col[0]}+1 WHERE id=?", (cost, uid))
    return jsonify(state(uid))

@app.post("/api/card")
def api_card():
    uid = auth(); d = card_defs().get(request.json.get("id")) or abort(400)
    cost = card_cost(d, card_levels(uid).get(d["id"], 0))
    if q("SELECT coins FROM users WHERE id=?", (uid,), one=True)["coins"] < cost: err("Not enough points")
    q("UPDATE users SET coins=coins-? WHERE id=?", (cost, uid))
    q("INSERT INTO cards VALUES(?,?,1) ON CONFLICT(uid,card) DO UPDATE SET lvl=lvl+1", (uid, d["id"]))
    return jsonify(state(uid))

@app.post("/api/daily")
def api_daily():
    uid = auth(); s = state(uid)
    if not s["daily_ready"]: err("Daily reward already claimed")
    q("UPDATE users SET coins=coins+?, streak=?, last_daily=? WHERE id=?", (s["daily_reward"], s["streak"] + 1, time.strftime("%Y-%m-%d"), uid))
    return jsonify(state(uid))

@app.post("/api/boost")
def api_boost():
    uid = auth(); kind = request.json.get("type")
    u = q("SELECT * FROM users WHERE id=?", (uid,), one=True); mx = cfg("max_boosts")
    if kind == "refill":
        if u["refill_used"] >= mx: err("No full-energy boosts left today")
        q("UPDATE users SET energy=?, refill_used=refill_used+1 WHERE id=?", (max_energy(u), uid))
    elif kind == "frenzy":
        if u["frenzy_used"] >= mx: err("No Frenzy boosts left today")
        if u["frenzy_until"] > time.time(): err("Frenzy is already active")
        q("UPDATE users SET frenzy_until=?, frenzy_used=frenzy_used+1 WHERE id=?", (time.time() + cfg("frenzy_sec"), uid))
    else: abort(400)
    return jsonify(state(uid))

@app.post("/api/task/start")
def api_task_start():
    uid = auth(); tid = int(request.json.get("id", 0))
    q("INSERT OR IGNORE INTO task_prog(uid,task,started,done) VALUES(?,?,?,0)", (uid, tid, time.time()))
    q("UPDATE task_prog SET started=? WHERE uid=? AND task=? AND started=0", (time.time(), uid, tid))
    return jsonify(state(uid))

@app.post("/api/task")
def api_task():
    uid = auth(); tid = int(request.json.get("id", 0))
    t = q("SELECT * FROM task_defs WHERE id=? AND enabled=1", (tid,), one=True) or abort(404)
    p = q("SELECT * FROM task_prog WHERE uid=? AND task=?", (uid, tid), one=True)
    if p and p["done"]: err("Already claimed")
    if t["kind"] == "invite":
        if state(uid)["ref_count"] < t["need"]: err("Invite more friends first")
    elif not p or not p["started"] or time.time() - p["started"] < TASK_WAIT:
        err("Open the link and wait a few seconds first")
    q("INSERT INTO task_prog(uid,task,started,done) VALUES(?,?,0,1) ON CONFLICT(uid,task) DO UPDATE SET done=1", (uid, tid))
    q("UPDATE users SET coins=coins+? WHERE id=?", (t["reward"], uid))
    return jsonify(state(uid))

@app.post("/api/promo")
def api_promo():
    uid = auth(); code = (request.json.get("code") or "").strip().upper()
    p = q("SELECT * FROM promos WHERE code=? AND enabled=1", (code,), one=True)
    if not p or (p["max_uses"] and p["uses"] >= p["max_uses"]): err("Invalid or expired code")
    if q("SELECT 1 FROM promo_used WHERE uid=? AND code=?", (uid, code), one=True): err("You already used this code")
    q("INSERT INTO promo_used VALUES(?,?)", (uid, code))
    q("UPDATE promos SET uses=uses+1 WHERE code=?", (code,))
    q("UPDATE users SET coins=coins+? WHERE id=?", (p["reward"], uid))
    return jsonify(state(uid))

@app.post("/api/friends")
def api_friends():
    uid = auth()
    return jsonify([dict(name=r["name"], coins=int(r["coins"])) for r in
                    q("SELECT name,coins FROM users WHERE referrer=? ORDER BY created DESC LIMIT 50", (uid,))])

@app.post("/api/leaderboard")
def api_leaderboard():
    uid = auth()
    rows = q("SELECT id,name,coins FROM users WHERE banned=0 ORDER BY coins DESC LIMIT 20")
    return jsonify(top=[dict(id=r["id"], name=r["name"], coins=int(r["coins"])) for r in rows], my_id=uid)

@app.get("/api/admin/stats")
def admin_stats():
    admin(); day = time.time() - 86400
    one = lambda sql, *a: q(sql, a, one=True)[0] or 0
    return jsonify(users=one("SELECT COUNT(*) FROM users"), new_24h=one("SELECT COUNT(*) FROM users WHERE created>?", day),
                   active_24h=one("SELECT COUNT(*) FROM users WHERE last_seen>?", day), banned=one("SELECT COUNT(*) FROM users WHERE banned=1"),
                   coins=int(one("SELECT SUM(coins) FROM users")), referrals=one("SELECT SUM(ref_count) FROM users"),
                   cards_bought=one("SELECT SUM(lvl) FROM cards"), tasks_done=one("SELECT COUNT(*) FROM task_prog WHERE done=1"),
                   promo_uses=one("SELECT COUNT(*) FROM promo_used"))

@app.post("/api/admin/users")
def admin_users():
    admin(); d = request.json or {}; s = (d.get("q") or "").strip(); off = int(d.get("page", 0)) * 20
    rows = q("SELECT id,name,coins,tap_lvl,ref_count,banned,last_seen FROM users WHERE CAST(id AS TEXT)=? OR name LIKE ? "
             "ORDER BY coins DESC LIMIT 20 OFFSET ?", (s, f"%{s}%", off)) if s else \
           q("SELECT id,name,coins,tap_lvl,ref_count,banned,last_seen FROM users ORDER BY coins DESC LIMIT 20 OFFSET ?", (off,))
    return jsonify([dict(r) for r in rows])

@app.post("/api/admin/user")
def admin_user():
    admin(); d = request.json; uid = int(d["id"]); act = d["action"]; val = d.get("value")
    if act == "add": q("UPDATE users SET coins=coins+? WHERE id=?", (float(val), uid))
    elif act == "set": q("UPDATE users SET coins=? WHERE id=?", (float(val), uid))
    elif act in ("ban", "unban"): q("UPDATE users SET banned=? WHERE id=?", (1 if act == "ban" else 0, uid))
    elif act == "reset":
        q("UPDATE users SET coins=0, energy=?, tap_lvl=1, energy_lvl=1, regen_lvl=1, streak=0, last_daily='' WHERE id=?", (cfg("base_energy"), uid))
        q("DELETE FROM cards WHERE uid=?", (uid,))
    elif act == "msg":
        try: bot.send_message(uid, str(val))
        except Exception as e: err(f"Could not send: {e}")
    else: abort(400)
    return jsonify(ok=True)

@app.route("/api/admin/settings", methods=["GET", "POST"])
def admin_settings():
    admin()
    if request.method == "POST":
        for k, v in request.json.items():
            if k in DEFAULTS: q("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(v)))
    return jsonify({k: cfg(k) for k in DEFAULTS})

TABLES = {"cards": ("card_defs", ("id", "name", "icon", "base_cost", "base_profit", "enabled")),
          "tasks": ("task_defs", ("id", "title", "reward", "kind", "need", "url", "enabled")),
          "promos": ("promos", ("code", "reward", "max_uses", "uses", "enabled"))}

@app.route("/api/admin/<t>", methods=["GET", "POST", "DELETE"])
def admin_crud(t):
    admin()
    if t not in TABLES: abort(404)
    tbl, cols = TABLES[t]; pk = cols[0]
    if request.method == "GET": return jsonify([dict(r) for r in q(f"SELECT * FROM {tbl}")])
    d = request.json
    if request.method == "DELETE":
        q(f"DELETE FROM {tbl} WHERE {pk}=?", (d[pk],)); return jsonify(ok=True)
    row = {c: d[c] for c in cols if d.get(c) is not None and not (c == pk and d[c] == "")}
    if t == "promos" and "code" in row: row["code"] = str(row["code"]).strip().upper()
    if t == "cards" and "id" in row: row["id"] = str(row["id"]).strip().lower().replace(" ", "_")
    if pk not in row and t != "tasks": err("Missing key")
    names = ",".join(row); marks = ",".join("?" * len(row))
    upd = ",".join(f"{c}=excluded.{c}" for c in row if c != pk)
    q(f"INSERT INTO {tbl}({names}) VALUES({marks})" + (f" ON CONFLICT({pk}) DO UPDATE SET {upd}" if pk in row and upd else ""), tuple(row.values()))
    return jsonify(ok=True)

BC = dict(running=False, sent=0, failed=0, total=0)

def run_broadcast(text):
    ids = [r["id"] for r in q("SELECT id FROM users WHERE banned=0")]
    BC.update(running=True, sent=0, failed=0, total=len(ids))
    for i in ids:
        try: bot.send_message(i, text); BC["sent"] += 1
        except Exception: BC["failed"] += 1
        time.sleep(0.05)
    BC["running"] = False

@app.route("/api/admin/broadcast", methods=["GET", "POST"])
def admin_broadcast():
    admin()
    if request.method == "POST":
        if BC["running"]: err("A broadcast is already running")
        threading.Thread(target=run_broadcast, args=(request.json["text"],), daemon=True).start()
    return jsonify(BC)

@app.post("/api/admin/gift")
def admin_gift():
    admin(); q("UPDATE users SET coins=coins+? WHERE banned=0", (float(request.json["amount"]),))
    return jsonify(ok=True)


bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
BOT_USERNAME = ""

def play_markup():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Play KiwiTap 🥝", web_app=types.WebAppInfo(WEBAPP_URL)))
    return kb

@bot.message_handler(commands=["start"])
def start(m):
    uid, parts = m.from_user.id, m.text.split()
    is_new = q("SELECT 1 FROM users WHERE id=?", (uid,), one=True) is None
    get_user(uid, m.from_user.first_name)
    if is_new and len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            ref = int(parts[1][4:])
            if ref != uid and q("SELECT 1 FROM users WHERE id=?", (ref,), one=True):
                bonus = cfg("ref_premium_bonus") if getattr(m.from_user, "is_premium", False) else cfg("ref_bonus")
                q("UPDATE users SET referrer=?, coins=coins+? WHERE id=?", (ref, bonus, uid))
                q("UPDATE users SET coins=coins+?, ref_count=ref_count+1 WHERE id=?", (bonus, ref))
                bot.send_message(ref, f"{m.from_user.first_name} joined with your link! +{int(bonus):,} points")
        except ValueError: pass
    caption = str(cfg("welcome_text")).replace("{name}", m.from_user.first_name)
    with open(WELCOME_PHOTO, "rb") as photo:
        bot.send_photo(m.chat.id, photo, caption=caption, reply_markup=play_markup())

@bot.message_handler(commands=["balance"])
def balance(m):
    get_user(m.from_user.id, m.from_user.first_name); sync(m.from_user.id)
    bot.reply_to(m, f"Balance: <b>{int(state(m.from_user.id)['coins']):,}</b> points")

@bot.message_handler(commands=["admin"])
def admin_cmd(m):
    if m.from_user.id not in ADMIN_IDS: return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Open admin panel", web_app=types.WebAppInfo(WEBAPP_URL + "/admin")))
    bot.send_message(m.chat.id, "Admin panel:", reply_markup=kb)

if __name__ == "__main__":
    BOT_USERNAME = bot.get_me().username
    try: bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp("Play", types.WebAppInfo(WEBAPP_URL)))
    except Exception as e: print("menu button:", e)
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))