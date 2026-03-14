from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from database import init_db, get_db
from pipedrive import post_note_to_deal, get_pipedrive_users
from scheduler import start_scheduler
import os
import jwt
import datetime
import logging
import requests as req
from base64 import b64encode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

PIPEDRIVE_CLIENT_SECRET = os.getenv("PIPEDRIVE_CLIENT_SECRET")
PIPEDRIVE_CLIENT_ID = os.getenv("PIPEDRIVE_CLIENT_ID")
BACKEND_URL = os.getenv("BACKEND_URL", "https://creativechatbox-production.up.railway.app")

PIPEDRIVE_TOKEN_URL = os.getenv("PIPEDRIVE_TOKEN_URL", "https://oauth.pipedrive.com/oauth/token")

def verify_jwt(token):
    try:
        decoded = jwt.decode(token, PIPEDRIVE_CLIENT_SECRET, algorithms=["HS256"])
        return decoded
    except Exception as e:
        logger.warning(f"JWT verification failed: {e}")
        return None

def _basic_auth_header():
    credentials = b64encode(f"{PIPEDRIVE_CLIENT_ID}:{PIPEDRIVE_CLIENT_SECRET}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}

def exchange_code_for_tokens(code):
    """Exchange an authorization code for access + refresh tokens."""
    resp = req.post(
        PIPEDRIVE_TOKEN_URL,
        headers=_basic_auth_header(),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{BACKEND_URL}/callback",
        },
    )
    resp.raise_for_status()
    return resp.json()

def refresh_access_token(refresh_token):
    """Use a refresh token to obtain a new access token."""
    resp = req.post(
        PIPEDRIVE_TOKEN_URL,
        headers=_basic_auth_header(),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    resp.raise_for_status()
    return resp.json()

def store_tokens(token_data):
    """Persist OAuth tokens to the database (single-row private-app table)."""
    import sqlite3
    from database import DATABASE
    expires_at = (
        datetime.datetime.utcnow()
        + datetime.timedelta(seconds=token_data.get("expires_in", 3600))
    ).isoformat()
    db = sqlite3.connect(DATABASE)
    db.execute("""
        INSERT INTO oauth_tokens (id, access_token, refresh_token, api_domain, token_type, expires_at, updated_at)
        VALUES (1, :access_token, :refresh_token, :api_domain, :token_type, :expires_at, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            access_token = excluded.access_token,
            refresh_token = excluded.refresh_token,
            api_domain = excluded.api_domain,
            token_type = excluded.token_type,
            expires_at = excluded.expires_at,
            updated_at = excluded.updated_at
    """, {
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "api_domain": token_data.get("api_domain", ""),
        "token_type": token_data.get("token_type", "Bearer"),
        "expires_at": expires_at,
    })
    db.commit()
    db.close()
    logger.info("OAuth tokens stored successfully")

def get_valid_access_token():
    """Return a valid access token, refreshing it if expired."""
    import sqlite3
    from database import DATABASE
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM oauth_tokens WHERE id = 1").fetchone()
    db.close()
    if not row:
        return None
    expires_at = datetime.datetime.fromisoformat(row["expires_at"])
    if datetime.datetime.utcnow() >= expires_at - datetime.timedelta(minutes=5):
        logger.info("Access token expired, refreshing...")
        try:
            token_data = refresh_access_token(row["refresh_token"])
            store_tokens(token_data)
            return token_data["access_token"]
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return None
    return row["access_token"]

# ─── THREADS ─────────────────────────────────────────────────────────────────

@app.route("/threads/<int:deal_id>", methods=["GET"])
def get_threads(deal_id):
    db = get_db()
    threads = db.execute("""
        SELECT t.*, 
               COUNT(CASE WHEN m.created_at > COALESCE(t.last_read_at, '1970-01-01') THEN 1 END) as unread_count,
               (SELECT content FROM messages WHERE thread_id = t.id ORDER BY created_at DESC LIMIT 1) as last_message,
               (SELECT created_at FROM messages WHERE thread_id = t.id ORDER BY created_at DESC LIMIT 1) as last_message_at
        FROM threads t
        LEFT JOIN messages m ON m.thread_id = t.id
        WHERE t.deal_id = ?
        GROUP BY t.id
        ORDER BY COALESCE(last_message_at, t.created_at) DESC
    """, (deal_id,)).fetchall()

    result = []
    for t in threads:
        participants = db.execute("""
            SELECT user_id, user_name FROM participants WHERE thread_id = ?
        """, (t["id"],)).fetchall()
        result.append({
            "id": t["id"],
            "deal_id": t["deal_id"],
            "title": t["title"],
            "status": t["status"],
            "created_by": t["created_by"],
            "created_by_name": t["created_by_name"],
            "created_at": t["created_at"],
            "last_message": t["last_message"],
            "last_message_at": t["last_message_at"],
            "unread_count": t["unread_count"],
            "participants": [{"user_id": p["user_id"], "user_name": p["user_name"]} for p in participants]
        })
    return jsonify(result)


@app.route("/threads", methods=["POST"])
def create_thread():
    data = request.json
    deal_id = data.get("deal_id")
    title = data.get("title", "New Thread")
    created_by = data.get("user_id")
    created_by_name = data.get("user_name")
    participants = data.get("participants", [])

    if not all([deal_id, created_by, created_by_name]):
        return jsonify({"error": "Missing required fields"}), 400

    db = get_db()
    cursor = db.execute("""
        INSERT INTO threads (deal_id, title, created_by, created_by_name, status, created_at, last_activity_at)
        VALUES (?, ?, ?, ?, 'open', datetime('now'), datetime('now'))
    """, (deal_id, title, created_by, created_by_name))
    thread_id = cursor.lastrowid

    db.execute("INSERT INTO participants (thread_id, user_id, user_name) VALUES (?, ?, ?)",
               (thread_id, created_by, created_by_name))

    for p in participants:
        if p["user_id"] != created_by:
            db.execute("INSERT INTO participants (thread_id, user_id, user_name) VALUES (?, ?, ?)",
                       (thread_id, p["user_id"], p["user_name"]))

    db.commit()
    logger.info(f"Thread {thread_id} created for deal {deal_id} by {created_by_name}")
    return jsonify({"id": thread_id, "status": "created"}), 201


@app.route("/threads/<int:thread_id>/close", methods=["POST"])
def close_thread(thread_id):
    data = request.json
    closed_by = data.get("user_name", "System")
    auto_closed = data.get("auto_closed", False)

    db = get_db()
    thread = db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    if thread["status"] == "closed":
        return jsonify({"error": "Thread already closed"}), 400

    messages = db.execute("""
        SELECT user_name, content, created_at FROM messages
        WHERE thread_id = ? ORDER BY created_at ASC
    """, (thread_id,)).fetchall()

    participants = db.execute("""
        SELECT user_id, user_name FROM participants WHERE thread_id = ?
    """, (thread_id,)).fetchall()

    note = format_note(thread, messages, participants, closed_by, auto_closed)

    try:
        post_note_to_deal(thread["deal_id"], note)
        logger.info(f"Note posted to deal {thread['deal_id']} for thread {thread_id}")
    except Exception as e:
        logger.error(f"Failed to post note to Pipedrive: {e}")

    db.execute("""
        UPDATE threads SET status = 'closed', closed_at = datetime('now') WHERE id = ?
    """, (thread_id,))
    db.commit()

    return jsonify({"status": "closed", "thread_id": thread_id})


def format_note(thread, messages, participants, closed_by, auto_closed):
    participant_names = " ".join([f"@{p['user_name']}" for p in participants])
    close_reason = "Auto-closed after 24hrs inactivity" if auto_closed else f"Closed by {closed_by}"

    lines = [
        f"── Team Chat: {thread['title']} ──────────────────────",
        f"Deal Chat  |  {participant_names}",
        f"Started: {thread['created_at']}",
        "─────────────────────────────────────────────────────",
        ""
    ]

    for msg in messages:
        time = msg["created_at"][11:16]
        date = msg["created_at"][:10]
        lines.append(f"[{date} {time}]  {msg['user_name']}: {msg['content']}")

    lines.extend([
        "",
        "─────────────────────────────────────────────────────",
        f"[{close_reason}]"
    ])

    return "\n".join(lines)


# ─── MESSAGES ────────────────────────────────────────────────────────────────

@app.route("/threads/<int:thread_id>/messages", methods=["GET"])
def get_messages(thread_id):
    db = get_db()
    messages = db.execute("""
        SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at ASC
    """, (thread_id,)).fetchall()
    return jsonify([dict(m) for m in messages])


@app.route("/threads/<int:thread_id>/messages", methods=["POST"])
def send_message(thread_id):
    data = request.json
    user_id = data.get("user_id")
    user_name = data.get("user_name")
    content = data.get("content", "").strip()

    if not all([user_id, user_name, content]):
        return jsonify({"error": "Missing required fields"}), 400

    db = get_db()
    thread = db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    if thread["status"] == "closed":
        return jsonify({"error": "Thread is closed"}), 400

    cursor = db.execute("""
        INSERT INTO messages (thread_id, user_id, user_name, content, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (thread_id, user_id, user_name, content))
    message_id = cursor.lastrowid

    db.execute("""
        UPDATE threads SET last_activity_at = datetime('now') WHERE id = ?
    """, (thread_id,))

    existing = db.execute("""
        SELECT 1 FROM participants WHERE thread_id = ? AND user_id = ?
    """, (thread_id, user_id)).fetchone()
    if not existing:
        db.execute("INSERT INTO participants (thread_id, user_id, user_name) VALUES (?, ?, ?)",
                   (thread_id, user_id, user_name))

    db.commit()

    msg = db.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return jsonify(dict(msg)), 201


# ─── USERS ───────────────────────────────────────────────────────────────────

@app.route("/users", methods=["GET"])
def get_users():
    try:
        users = get_pipedrive_users()
        return jsonify(users)
    except Exception as e:
        logger.error(f"Failed to fetch users: {e}")
        return jsonify([]), 200


# ─── UNREAD COUNT ─────────────────────────────────────────────────────────────

@app.route("/unread/<int:user_id>", methods=["GET"])
def get_unread_count(user_id):
    db = get_db()
    count = db.execute("""
        SELECT COUNT(*) as cnt FROM messages m
        JOIN threads t ON t.id = m.thread_id
        JOIN participants p ON p.thread_id = m.thread_id AND p.user_id = ?
        WHERE t.status = 'open'
        AND m.user_id != ?
        AND m.created_at > COALESCE((
            SELECT last_read_at FROM read_receipts 
            WHERE thread_id = m.thread_id AND user_id = ?
        ), '1970-01-01')
    """, (user_id, user_id, user_id)).fetchone()
    return jsonify({"unread": count["cnt"]})


@app.route("/threads/<int:thread_id>/read", methods=["POST"])
def mark_read(thread_id):
    data = request.json
    user_id = data.get("user_id")
    db = get_db()
    db.execute("""
        INSERT OR REPLACE INTO read_receipts (thread_id, user_id, last_read_at)
        VALUES (?, ?, datetime('now'))
    """, (thread_id, user_id))
    db.commit()
    return jsonify({"status": "ok"})


# ─── HEALTH ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.datetime.utcnow().isoformat()})


# ─── FRONTEND ────────────────────────────────────────────────────────────────

@app.route("/panel")
def panel():
    # Inject the real backend URL so the frontend doesn't need a hardcoded placeholder
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    html = html.replace(
        "const BACKEND = 'https://your-railway-app.railway.app'; // ← UPDATE THIS",
        f"const BACKEND = '{BACKEND_URL}';"
    )
    from flask import Response
    return Response(html, mimetype='text/html')


# ─── OAUTH ───────────────────────────────────────────────────────────────────

@app.route("/install")
def install():
    from flask import redirect
    auth_url = (
        f"https://oauth.pipedrive.com/oauth/authorize"
        f"?client_id={PIPEDRIVE_CLIENT_ID}"
        f"&redirect_uri={BACKEND_URL}/callback"
    )
    return redirect(auth_url)

@app.route("/")
def index():
    code = request.args.get("code")
    if code:
        # Pipedrive may use "/" as the redirect URI — handle it the same as /callback
        try:
            token_data = exchange_code_for_tokens(code)
            store_tokens(token_data)
            logger.info("OAuth installation completed via / route")
            return "Deal Chat installed successfully! You can close this tab and return to Pipedrive.", 200
        except Exception as e:
            logger.error(f"OAuth token exchange failed: {e}")
            return f"Installation failed: {e}", 500
    return "Deal Chat API running.", 200

@app.route("/callback")
def callback():
    code = request.args.get("code")
    error = request.args.get("error")
    if error:
        logger.warning(f"OAuth error from Pipedrive: {error}")
        return f"Authorization denied: {error}", 400
    if not code:
        return "No authorization code received.", 400
    try:
        token_data = exchange_code_for_tokens(code)
        store_tokens(token_data)
        logger.info("OAuth installation completed via /callback route")
        return "Deal Chat installed successfully! You can close this tab and return to Pipedrive.", 200
    except Exception as e:
        logger.error(f"OAuth token exchange failed: {e}")
        return f"Installation failed: {e}", 500


# ─── STARTUP ─────────────────────────────────────────────────────────────────

init_db()
start_scheduler(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)