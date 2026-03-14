import requests
import os
import logging

logger = logging.getLogger(__name__)

PIPEDRIVE_API_TOKEN = os.getenv("PIPEDRIVE_API_TOKEN")
PIPEDRIVE_COMPANY_DOMAIN = os.getenv("PIPEDRIVE_COMPANY_DOMAIN")


def _get_auth():
    """
    Return (headers, params) for Pipedrive API calls.
    Prefers OAuth access token; falls back to personal API token.
    """
    try:
        from app import get_valid_access_token
        access_token = get_valid_access_token()
        if access_token:
            return {"Authorization": f"Bearer {access_token}"}, {}
    except Exception:
        pass
    # Fallback: personal API token
    return {}, {"api_token": PIPEDRIVE_API_TOKEN}


def _base_url(api_domain=None):
    if api_domain:
        domain = api_domain.replace("https://", "").replace("http://", "").rstrip("/")
        return f"https://{domain}/api/v1"
    return f"https://{PIPEDRIVE_COMPANY_DOMAIN}.pipedrive.com/api/v1"


def _api_domain_from_db():
    """Retrieve the api_domain stored during OAuth install."""
    try:
        import sqlite3
        from database import DATABASE
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT api_domain FROM oauth_tokens WHERE id = 1").fetchone()
        db.close()
        if row and row["api_domain"]:
            return row["api_domain"]
    except Exception:
        pass
    return None


def post_note_to_deal(deal_id, content):
    api_domain = _api_domain_from_db()
    url = f"{_base_url(api_domain)}/notes"
    headers, params = _get_auth()
    payload = {
        "content": content,
        "deal_id": deal_id,
        "pinned_to_deal_flag": 0,
    }
    response = requests.post(url, json=payload, headers=headers, params=params)
    response.raise_for_status()
    logger.info(f"Note posted to deal {deal_id}")
    return response.json()


def get_pipedrive_users():
    api_domain = _api_domain_from_db()
    url = f"{_base_url(api_domain)}/users"
    headers, params = _get_auth()
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    if data.get("success"):
        return [
            {"id": u["id"], "name": u["name"], "email": u["email"]}
            for u in data.get("data", [])
            if u.get("active_flag")
        ]
    return []
