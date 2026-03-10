import requests
import os
import logging

logger = logging.getLogger(__name__)

PIPEDRIVE_API_TOKEN = os.getenv("PIPEDRIVE_API_TOKEN")
PIPEDRIVE_COMPANY_DOMAIN = os.getenv("PIPEDRIVE_COMPANY_DOMAIN")

def base_url():
    return f"https://{PIPEDRIVE_COMPANY_DOMAIN}.pipedrive.com/api/v1"

def post_note_to_deal(deal_id, content):
    url = f"{base_url()}/notes"
    payload = {
        "content": content,
        "deal_id": deal_id,
        "pinned_to_deal_flag": 0
    }
    response = requests.post(url, json=payload, params={"api_token": PIPEDRIVE_API_TOKEN})
    response.raise_for_status()
    logger.info(f"Note posted to deal {deal_id}")
    return response.json()

def get_pipedrive_users():
    url = f"{base_url()}/users"
    response = requests.get(url, params={"api_token": PIPEDRIVE_API_TOKEN})
    response.raise_for_status()
    data = response.json()
    if data.get("success"):
        return [
            {"id": u["id"], "name": u["name"], "email": u["email"]}
            for u in data.get("data", [])
            if u.get("active_flag")
        ]
    return []
