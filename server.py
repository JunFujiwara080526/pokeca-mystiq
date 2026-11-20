#!/usr/bin/env python3
"""
Mystiq - 謎解き大会 回答・進行システム
外部依存なし（Python 3.9+ 標準ライブラリのみ）
"""
import cgi
import base64
import hashlib
import hmac
import html
import http.server
import io
import json
import os
import re
import secrets
import socketserver
import sqlite3
import sys
import time
import unicodedata
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "mystiq.db")
PUZZLE_PATH = os.path.join(DATA_DIR, "puzzle.json")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
HOST = os.environ.get("HOST", "")
PORT = int(os.environ.get("PORT") or os.environ.get("MYSTIQ_PORT") or 8080)
ADMIN_PASSWORD_FILE = os.path.join(DATA_DIR, "admin_password.txt")
ADMIN_HASH_FILE = os.path.join(DATA_DIR, "admin_password_hash.json")
SESSION_TTL = 12 * 3600
ADMIN_SESSIONS = {}

RATE_LIMIT_WRONGS = 3      # 不正解何回でクールダウン？
COOLDOWN_SECONDS = 30     # クールダウン秒数

DEFAULT_CONFIG = {
    "competition_started": True,   # 解答受付中フラグ
    "title": "月例 謎解きミッション",
    "rate_limit_wrongs": RATE_LIMIT_WRONGS,
    "cooldown_seconds": COOLDOWN_SECONDS,
}

# ----------------- 管理者認証 -----------------
def hash_password(password: str) -> dict:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return {"algo": "pbkdf2_sha256",
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": base64.b64encode(dk).decode("ascii"),
            "iters": 200_000}

def verify_password(password: str, record: dict) -> bool:
    try:
        salt = base64.b64decode(record["salt"].encode("ascii"))
        expected = base64.b64decode(record["hash"].encode("ascii"))
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 int(record.get("iters", 200_000)))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False

def get_admin_password_info():
    env_pw = os.environ.get("ADMIN_PASSWORD", "").strip()
    if env_pw:
        return {"type": "env", "record": hash_password(env_pw), "source": "env"}
    rec = load_json(ADMIN_HASH_FILE, None)
    if rec and isinstance(rec, dict) and "hash" in rec:
        return {"type": "hash", "record": rec, "source": "saved"}
    if os.path.exists(ADMIN_PASSWORD_FILE):
        try:
            with open(ADMIN_PASSWORD_FILE, "r", encoding="utf-8") as f:
                pw = f.read().strip()
            if pw:
                return {"type": "plain", "password": pw, "source": "file"}
        except OSError:
            pass
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    initial = "".join(secrets.choice(alphabet) for _ in range(16))
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ADMIN_PASSWORD_FILE, "w", encoding="utf-8") as f:
        f.write(initial)
    return {"type": "plain", "password": initial, "source": "file", "created": True}

def check_admin_password(password: str) -> bool:
    info = get_admin_password_info()
    if info["type"] in ("env", "hash"):
        return verify_password(password, info["record"])
    return hmac.compare_digest(password.encode("utf-8"),
                               info["password"].encode("utf-8"))

def set_admin_password(new_password: str):
    save_json(ADMIN_HASH_FILE, hash_password(new_password))
    if os.path.exists(ADMIN_PASSWORD_FILE):
        try:
            os.remove(ADMIN_PASSWORD_FILE)
        except OSError:
            pass

def create_admin_session() -> str:
    token = secrets.token_hex(32)
    ADMIN_SESSIONS[token] = time.time() + SESSION_TTL
    return token

def check_admin_token(token: str) -> bool:
    if not token:
        return False
    exp = ADMIN_SESSIONS.get(token)
    if exp is None or time.time() > exp:
        ADMIN_SESSIONS.pop(token, None)
        return False
    return True

def revoke_admin_token(token: str):
    ADMIN_SESSIONS.pop(token, None)

# ----------------- DB -----------------
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    with get_db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at REAL NOT NULL,
            finished_at REAL
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id TEXT NOT NULL,
            stage_id INTEGER NOT NULL,
            answer TEXT NOT NULL,
            is_correct INTEGER NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clears (
            player_id TEXT NOT NULL,
            stage_id INTEGER NOT NULL,
            cleared_at REAL NOT NULL,
            PRIMARY KEY (player_id, stage_id)
        );
        CREATE TABLE IF NOT EXISTS hints (
            stage_id INTEGER NOT NULL,
            hint_index INTEGER NOT NULL,
            unlocked_at REAL NOT NULL,
            PRIMARY KEY (stage_id, hint_index)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            message TEXT NOT NULL,
            payload TEXT,
            created_at REAL NOT NULL
        );
        """)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)

# ----------------- Helpers -----------------
def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_event(ev_type, message, payload=None):
    with get_db() as c:
        c.execute("INSERT INTO events (type, message, payload, created_at) VALUES (?,?,?,?)",
                  (ev_type, message, json.dumps(payload, ensure_ascii=False) if payload else None, time.time()))

def normalize(s: str) -> str:
    """表記ゆれ吸収: NFKC正規化・小文字化・空白/長音記号/中点/記号除去・ひらがな→カタカナ統一"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    # ひらがな → カタカナ (U+3041-3096 -> U+30A1-30F6)
    out = []
    for ch in s:
        code = ord(ch)
        if 0x3041 <= code <= 0x3096:
            out.append(chr(code + 0x60))
        else:
            out.append(ch)
    s = "".join(out)
    # 記号・空白除去
    s = re.sub(r"[\s\-\u30fb\u30fc\uff0d\uffe3_.,!?:;/'\"〜~ー＝=／]", "", s)
    return s

def check_answer(player_input: str, puzzle_data: dict, stage_id: int):
    stage = next((st for st in puzzle_data.get("stages", []) if st["id"] == stage_id), None)
    if not stage:
        return False, "不正なステージです", "bad_stage"
    norm_input = normalize(player_input)
    if not norm_input:
        return False, "回答を入力してください", "empty"
    for ans in stage.get("answers", []):
        if normalize(ans) == norm_input:
            return True, "正解！お見事です！", "correct"
    for near in stage.get("nearAnswers", []):
        if normalize(near.get("input", "")) == norm_input:
            return False, near.get("message", "惜しい！"), "near"
    return False, "不正解...もう一度考えてみよう！", "wrong"

def get_cooldown(player_id: str, stage_id: int):
    cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
    limit = cfg.get("rate_limit_wrongs", RATE_LIMIT_WRONGS)
    cd = cfg.get("cooldown_seconds", COOLDOWN_SECONDS)
    with get_db() as c:
        rows = c.execute(
            "SELECT is_correct, created_at FROM attempts WHERE player_id=? AND stage_id=? ORDER BY id DESC LIMIT ?",
            (player_id, stage_id, limit),
        ).fetchall()
    if len(rows) < limit:
        return 0, 0
    if all(r["is_correct"] == 0 for r in rows):
        last_wrong = rows[0]["created_at"]
        remaining = last_wrong + cd - time.time()
        if remaining > 0:
            return int(remaining), limit
    return 0, 0

def player_progress(player_id: str):
    puzzle = load_json(PUZZLE_PATH, {})
    stages = puzzle.get("stages", [])
    with get_db() as c:
        cleared = {r["stage_id"] for r in c.execute(
            "SELECT stage_id FROM clears WHERE player_id=?", (player_id,)).fetchall()}
    current = None
    for st in stages:
        if st["id"] not in cleared:
            current = st["id"]
            break
    finished = current is None and len(stages) > 0
    return {"current_stage_id": current, "cleared_stages": sorted(cleared), "finished": finished, "total": len(stages)}

# ----------------- HTTP Handler -----------------
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def log_message(self, fmt, *args):
        # 静音（必要ならsys.stderrに出力）
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ---------- GET ----------
    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        path = p.path
        qs = urllib.parse.parse_qs(p.query)

        if path.startswith("/api/"):
            try:
                self.handle_api_get(path, qs)
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
            return

        # アップロード画像配信
        if path.startswith("/uploads/"):
            fname = os.path.basename(path.replace("/uploads/", ""))
            fpath = os.path.join(UPLOADS_DIR, fname)
            if os.path.exists(fpath):
                self.serve_file(fpath)
            else:
                self.send_error(404)
            return

        # 静的ファイル配信
        super().do_GET()

    def serve_file(self, fpath):
        import mimetypes
        ctype = mimetypes.guess_type(fpath)[0] or "application/octet-stream"
        with open(fpath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def extract_admin_token(self):
        t = self.headers.get("X-Admin-Token", "").strip()
        if t:
            return t
        auth = self.headers.get("Authorization", "").strip()
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "mystiq_admin_token":
                return v.strip()
        return ""

    def require_admin(self, path):
        if not path.startswith("/api/admin/"):
            return True
        if path in ("/api/admin/login", "/api/admin/password/source"):
            return True
        if not check_admin_token(self.extract_admin_token()):
            self.send_json({"ok": False, "error": "認証が必要です", "login_required": True}, 401)
            return False
        return True

    def handle_api_get(self, path, qs):
        now = time.time()

        if path == "/api/healthz":
            self.send_json({"ok": True, "status": "healthy"})
            return

        if not self.require_admin(path):
            return

        if path == "/api/status":
            cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
            puzzle = load_json(PUZZLE_PATH, {})
            with get_db() as c:
                hints = [dict(r) for r in c.execute("SELECT stage_id, hint_index, unlocked_at FROM hints").fetchall()]
            self.send_json({"ok": True, "config": cfg, "stages_meta": [
                {"id": s["id"], "name": s.get("name"), "subtitle": s.get("subtitle")}
                for s in puzzle.get("stages", [])], "unlocked_hints": hints, "server_time": now})

        elif path == "/api/puzzle":
            # 参加者用パズル情報（正解は含まない！）
            puzzle = load_json(PUZZLE_PATH, {})
            with get_db() as c:
                hints = {(r["stage_id"], r["hint_index"]) for r in c.execute("SELECT stage_id, hint_index FROM hints").fetchall()}
            stages_safe = []
            for st in puzzle.get("stages", []):
                safe = {
                    "id": st["id"],
                    "name": st.get("name", ""),
                    "answerNote": st.get("answerNote", ""),
                    "hints": [
                        (h if (st["id"], i) in hints else None)
                        for i, h in enumerate(st.get("hints", []))
                    ],
                    "hintsTotal": len(st.get("hints", [])),
                }
                stages_safe.append(safe)
            cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
            self.send_json({
                "ok": True,
                "title": puzzle.get("title", cfg.get("title", "謎解き")),
                "clearMessage": puzzle.get("clearMessage", ""),
                "stages": stages_safe,
                "competition_started": cfg.get("competition_started", True),
            })

        elif path == "/api/player":
            pid = qs.get("id", [""])[0]
            if not pid:
                self.send_json({"ok": False, "error": "id required"}, 400); return
            with get_db() as c:
                pl = c.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
            if not pl:
                self.send_json({"ok": False, "error": "not found"}, 404); return
            prog = player_progress(pid)
            cd_sec, cd_limit = (get_cooldown(pid, prog["current_stage_id"]) if prog["current_stage_id"] else (0, 0))
            self.send_json({"ok": True, "player": dict(pl), "progress": prog,
                            "cooldown": {"seconds": cd_sec, "wrongs_limit": cd_limit}, "server_time": now})

        elif path == "/api/ranking":
            with get_db() as c:
                players = [dict(r) for r in c.execute("SELECT * FROM players").fetchall()]
                clears = [dict(r) for r in c.execute("SELECT * FROM clears").fetchall()]
                attempts = [dict(r) for r in c.execute("SELECT player_id, is_correct FROM attempts").fetchall()]
            puzzle = load_json(PUZZLE_PATH, {})
            stages = puzzle.get("stages", [])
            total_stages = len(stages)
            # 集計
            p_clears = {}
            for cl in clears:
                p_clears.setdefault(cl["player_id"], []).append(cl)
            wrongs = {}
            for a in attempts:
                if a["is_correct"] == 0:
                    wrongs[a["player_id"]] = wrongs.get(a["player_id"], 0) + 1
            rows = []
            for pl in players:
                clist = sorted(p_clears.get(pl["id"], []), key=lambda x: x["cleared_at"])
                n = len(clist)
                last_t = clist[-1]["cleared_at"] if clist else pl["created_at"]
                first_t = clist[0]["cleared_at"] if clist else pl["created_at"]
                elapsed = last_t - pl["created_at"]
                rows.append({
                    "id": pl["id"], "name": pl["name"], "created_at": pl["created_at"],
                    "cleared_count": n, "cleared_stages": [c["stage_id"] for c in clist],
                    "finished": n >= total_stages and total_stages > 0,
                    "last_cleared_at": last_t,
                    "elapsed": max(0, int(elapsed)),
                    "wrong_attempts": wrongs.get(pl["id"], 0),
                })
            # ソート: クリア数(降順) → 最終クリア時刻(昇順) → 開始時刻
            rows.sort(key=lambda r: (-r["cleared_count"], r["last_cleared_at"], r["created_at"]))
            for i, r in enumerate(rows, 1):
                r["rank"] = i
            self.send_json({"ok": True, "ranking": rows, "total_stages": total_stages,
                            "competition_started": load_json(CONFIG_PATH, DEFAULT_CONFIG).get("competition_started", True)})

        elif path == "/api/admin/data":
            # 管理画面用（正解・ヒント生データも含む）
            puzzle = load_json(PUZZLE_PATH, {})
            cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
            with get_db() as c:
                hints = [dict(r) for r in c.execute("SELECT * FROM hints").fetchall()]
                players = [dict(r) for r in c.execute("SELECT * FROM players ORDER BY created_at DESC").fetchall()]
                events = [dict(r) for r in c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 50").fetchall()]
                attempts = c.execute("SELECT COUNT(*) c FROM attempts").fetchone()["c"]
                clears = c.execute("SELECT COUNT(*) c FROM clears").fetchone()["c"]
            self.send_json({"ok": True, "puzzle": puzzle, "config": cfg, "hints": hints,
                            "players": players, "events": events,
                            "stats": {"attempts": attempts, "clears": clears, "players": len(players)}})

        elif path == "/api/admin/session":
            self.send_json({"ok": True})

        elif path == "/api/admin/password/source":
            info = get_admin_password_info()
            self.send_json({"ok": True, "source": info["source"], "managed_by_env": info["type"] == "env"})

        elif path == "/api/admin/backup":
            puzzle = load_json(PUZZLE_PATH, {})
            cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
            with get_db() as c:
                players = [dict(r) for r in c.execute("SELECT * FROM players").fetchall()]
                clears = [dict(r) for r in c.execute("SELECT * FROM clears").fetchall()]
                attempts = [dict(r) for r in c.execute("SELECT * FROM attempts").fetchall()]
                hints = [dict(r) for r in c.execute("SELECT * FROM hints").fetchall()]
                events = [dict(r) for r in c.execute("SELECT * FROM events").fetchall()]
            backup = {"puzzle": puzzle, "config": cfg, "players": players, "clears": clears,
                      "attempts": attempts, "hints": hints, "events": events, "exported_at": now}
            payload = json.dumps(backup, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="mystiq-backup-{int(now)}.json"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        elif path == "/api/announcement":
            with get_db() as c:
                row = c.execute(
                    "SELECT payload FROM events WHERE type='broadcast' ORDER BY id DESC LIMIT 1"
                ).fetchone()
            payload = json.loads(row["payload"] or "{}") if row else {}
            self.send_json({"ok": True, "message": payload.get("text", "")})

        elif path == "/api/events":
            since = float(qs.get("since", [0])[0])
            with get_db() as c:
                rows = [dict(r) for r in c.execute(
                    "SELECT * FROM events WHERE created_at > ? ORDER BY id ASC LIMIT 100", (since,)).fetchall()]
            self.send_json({"ok": True, "events": rows, "server_time": now})

        else:
            self.send_error(404)

    # ---------- POST ----------
    def do_POST(self):
        p = urllib.parse.urlparse(self.path)
        path = p.path
        ctype = self.headers.get("Content-Type", "")

        try:
            if "application/json" in ctype:
                data = json.loads(self.read_body().decode("utf-8")) if self.headers.get("Content-Length") else {}
            elif "multipart/form-data" in ctype:
                data = None  # 後で処理
            else:
                data = urllib.parse.parse_qs(self.read_body().decode("utf-8"))
            self.handle_api_post(path, data, ctype)
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "invalid json"}, 400)
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_api_post(self, path, data, ctype):
        now = time.time()

        if path == "/api/admin/login":
            pw = (data or {}).get("password", "")
            if check_admin_password(pw):
                token = create_admin_session()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"mystiq_admin_token={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Lax")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "token": token}, ensure_ascii=False).encode("utf-8"))
            else:
                time.sleep(0.3)
                self.send_json({"ok": False, "error": "パスワードが違います"}, 401)
            return

        if not self.require_admin(path):
            return

        if path == "/api/player/register":
            name = (data or {}).get("name", "").strip()
            if not name:
                self.send_json({"ok": False, "error": "名前を入力してください"}, 400); return
            import uuid
            pid = "p_" + uuid.uuid4().hex[:12]
            with get_db() as c:
                c.execute("INSERT INTO players (id, name, created_at) VALUES (?,?,?)", (pid, name, now))
            log_event("player_join", f"「{name}」が参戦しました！", {"player_id": pid, "name": name})
            self.send_json({"ok": True, "player": {"id": pid, "name": name, "created_at": now}})

        elif path == "/api/answer":
            cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
            if not cfg.get("competition_started", True):
                self.send_json({"ok": False, "reason": "not_started", "message": "現在は解答の受付を停止しています。"}, 400); return

            pid = (data or {}).get("player_id", "")
            stage_id = int((data or {}).get("stage_id", 0))
            ans_text = (data or {}).get("answer", "")
            if not pid or not stage_id:
                self.send_json({"ok": False, "error": "player_id / stage_id required"}, 400); return

            with get_db() as c:
                pl = c.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
            if not pl:
                self.send_json({"ok": False, "error": "プレイヤーが見つかりません"}, 404); return

            cd_sec, _ = get_cooldown(pid, stage_id)
            if cd_sec > 0:
                self.send_json({"ok": False, "reason": "cooldown", "cooldown": cd_sec,
                                "message": f"不正解が連続しました。あと {cd_sec} 秒後に再入力できます。"}, 429); return

            # すでにクリア済み？
            prog = player_progress(pid)
            if stage_id in prog["cleared_stages"]:
                self.send_json({"ok": True, "result": "already", "message": "このステージは既にクリア済みです。"}); return
            if prog["current_stage_id"] != stage_id:
                self.send_json({"ok": False, "reason": "not_current", "message": "現在のステージと異なります。"}, 400); return

            puzzle = load_json(PUZZLE_PATH, {})
            correct, msg, reason = check_answer(ans_text, puzzle, stage_id)

            with get_db() as c:
                c.execute("INSERT INTO attempts (player_id, stage_id, answer, is_correct, created_at) VALUES (?,?,?,?,?)",
                          (pid, stage_id, ans_text[:200], 1 if correct else 0, now))
                if correct:
                    c.execute("INSERT OR IGNORE INTO clears (player_id, stage_id, cleared_at) VALUES (?,?,?)",
                              (pid, stage_id, now))

            st_obj = next((s for s in puzzle.get("stages", []) if s["id"] == stage_id), {})
            st_name = st_obj.get("name", f"第{stage_id}問")
            if correct:
                log_event("clear", f"🎉 {pl['name']} が {st_name} を突破！",
                          {"player": pl["name"], "stage_id": stage_id, "stage_name": st_name})
                new_prog = player_progress(pid)
                if new_prog["finished"]:
                    with get_db() as c:
                        c.execute("UPDATE players SET finished_at=? WHERE id=?", (now, pid))
                    log_event("all_clear", f"🏆 【祝】{pl['name']} が全ステージクリア！",
                              {"player": pl["name"]})
            else:
                pass  # 速報に不正解は流さない

            new_prog = player_progress(pid)
            next_cd, _ = get_cooldown(pid, stage_id)
            self.send_json({
                "ok": True,
                "result": "correct" if correct else "wrong",
                "reason": reason,
                "message": msg,
                "cooldown": next_cd,
                "progress": new_prog,
                "next_stage_id": new_prog["current_stage_id"],
            })

        # ----- 管理系 -----
        elif path == "/api/admin/hint/toggle":
            st_id = int((data or {}).get("stage_id", 0))
            idx = int((data or {}).get("hint_index", -1))
            puzzle = load_json(PUZZLE_PATH, {})
            st_obj = next((s for s in puzzle.get("stages", []) if s["id"] == st_id), {})
            with get_db() as c:
                row = c.execute("SELECT * FROM hints WHERE stage_id=? AND hint_index=?", (st_id, idx)).fetchone()
                if row:
                    c.execute("DELETE FROM hints WHERE stage_id=? AND hint_index=?", (st_id, idx))
                    msg = f"ヒント{idx+1}を取り下げました"
                    state = False
                else:
                    c.execute("INSERT INTO hints (stage_id, hint_index, unlocked_at) VALUES (?,?,?)",
                              (st_id, idx, now))
                    state = True
                    msg = f"ヒント{idx+1}を公開しました"
            if state:
                hint_text = st_obj.get("hints", [""])[idx] if idx < len(st_obj.get("hints", [])) else ""
                log_event("hint", f"💡 {st_obj.get('name', '')} のヒント {idx+1} が公開されました！",
                          {"stage_id": st_id, "stage_name": st_obj.get("name", ""),
                           "hint_index": idx, "hint": hint_text})
            self.send_json({"ok": True, "stage_id": st_id, "hint_index": idx, "unlocked": state, "message": msg})

        elif path == "/api/admin/competition/toggle":
            cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
            cur = cfg.get("competition_started", True)
            cfg["competition_started"] = not cur
            save_json(CONFIG_PATH, cfg)
            m = "解答の受付を再開しました！" if cfg["competition_started"] else "解答の受付を一時停止しました。"
            log_event("competition_state", f"📢 {m}", {"started": cfg["competition_started"]})
            self.send_json({"ok": True, "competition_started": cfg["competition_started"]})

        elif path == "/api/admin/broadcast":
            msg = (data or {}).get("message", "").strip()
            if not msg:
                self.send_json({"ok": False, "error": "message required"}, 400); return
            log_event("broadcast", f"📣 主催者より: {msg}", {"text": msg})
            self.send_json({"ok": True})

        elif path == "/api/admin/reset":
            what = (data or {}).get("what", "")
            with get_db() as c:
                if what == "all":
                    c.executescript("DELETE FROM attempts; DELETE FROM clears; DELETE FROM players; DELETE FROM hints; DELETE FROM events;")
                    msg = "全データを初期化しました"
                elif what == "hints":
                    c.execute("DELETE FROM hints")
                    msg = "ヒント公開状態を初期化しました"
                elif what == "ranking":
                    c.executescript("DELETE FROM attempts; DELETE FROM clears; UPDATE players SET finished_at=NULL;")
                    msg = "解答履歴とランキングを初期化しました"
                else:
                    self.send_json({"ok": False, "error": "bad what"}, 400); return
            log_event("reset", f"⚠️ 運営がリセットを実行（{what}）")
            self.send_json({"ok": True, "message": msg})

        elif path == "/api/admin/puzzle/save":
            pz = (data or {}).get("puzzle")
            if not pz or "stages" not in pz:
                self.send_json({"ok": False, "error": "invalid puzzle json"}, 400); return
            save_json(PUZZLE_PATH, pz)
            log_event("puzzle_update", "📝 問題データが更新されました")
            self.send_json({"ok": True})

        elif path == "/api/admin/config/save":
            cfg = (data or {}).get("config")
            if not cfg:
                self.send_json({"ok": False, "error": "invalid config"}, 400); return
            save_json(CONFIG_PATH, cfg)
            self.send_json({"ok": True})

        elif path == "/api/admin/upload":
            # multipart画像アップロード（標準ライブラリのみでパース）
            ctype_h = self.headers.get("Content-Type", "")
            pdict = {}
            if "boundary=" in ctype_h:
                boundary = ctype_h.split("boundary=")[1].strip().encode("ascii")
            else:
                self.send_json({"ok": False, "error": "bad content type"}, 400); return
            body = self.read_body()
            parts = body.split(b"--" + boundary)
            saved = None
            for part in parts:
                if not part or part == b"--\r\n":
                    continue
                header_part, _, payload = part.lstrip(b"\r\n").partition(b"\r\n\r\n")
                payload = payload.rstrip(b"\r\n")
                hdr_text = header_part.decode("utf-8", errors="ignore")
                m = re.search(r'filename="([^"]+)"', hdr_text)
                if m:
                    fname = m.group(1)
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                        self.send_json({"ok": False, "error": "許可されていない画像形式です"}, 400); return
                    outname = f"img_{int(now*1000)}{ext}"
                    with open(os.path.join(UPLOADS_DIR, outname), "wb") as f:
                        f.write(payload)
                    saved = f"/uploads/{outname}"
            if saved:
                self.send_json({"ok": True, "url": saved})
            else:
                self.send_json({"ok": False, "error": "ファイルが見つかりません"}, 400)

        elif path == "/api/admin/logout":
            revoke_admin_token(self.extract_admin_token())
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "mystiq_admin_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))

        elif path == "/api/admin/password/change":
            info = get_admin_password_info()
            if info["type"] == "env":
                self.send_json({"ok": False, "error": "パスワードは環境変数ADMIN_PASSWORDで管理されています。Renderの管理画面から変更してください。"}, 400)
                return
            new_pw = (data or {}).get("new_password", "").strip()
            if len(new_pw) < 8:
                self.send_json({"ok": False, "error": "パスワードは8文字以上で設定してください"}, 400)
                return
            set_admin_password(new_pw)
            self.send_json({"ok": True, "message": "パスワードを変更しました"})

        else:
            self.send_error(404)

class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

def main():
    init_db()
    pw_info = get_admin_password_info()
    if pw_info.get("created"):
        print(f"[ADMIN] 初期管理者パスワードを生成しました: {pw_info['password']}")
    print(f"[ADMIN] パスワード管理元: {pw_info['source']}")
    os.chdir(BASE_DIR)
    with ReusableServer((HOST or "0.0.0.0", PORT), Handler) as httpd:
        print(f"MYSTIQ server running on port {PORT}")
        sys.stdout.flush()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    main()
