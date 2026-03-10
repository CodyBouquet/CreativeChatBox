# Deal Chat — Pipedrive Internal Messaging App

Internal deal-level chat for your Pipedrive CRM. Replaces task-based communication with threaded conversations directly on deal records.

---

## Features

- 💬 Multiple threads per deal
- 👥 Add team members to conversations
- 🔔 Notification badge on Pipedrive puzzle icon
- ⏰ 1hr inactivity reminder, 24hr auto-close
- 📋 Closed conversations post as timestamped notes on the deal
- 🔍 "My Chats" filter (Phase 2)

---

## Architecture

```
Pipedrive Panel (frontend/index.html)
        ↓ REST API
Railway (backend/app.py)
        ↓ Pipedrive API
Pipedrive (notes, users)
```

---

## Setup

### 1. Deploy Backend to Railway

1. Push `backend/` folder to a GitHub repo
2. Create new Railway project → Deploy from GitHub
3. Set environment variables in Railway dashboard:

```
PIPEDRIVE_API_TOKEN=your_token
PIPEDRIVE_COMPANY_DOMAIN=yourcompany
PIPEDRIVE_CLIENT_SECRET=your_app_client_secret
BACKEND_URL=https://your-app.railway.app
```

4. Note your Railway app URL (e.g. `https://deal-chat.railway.app`)

---

### 2. Create Pipedrive App

1. Go to https://developers.pipedrive.com
2. Create a Developer Sandbox account
3. Click "Create an app" → Private app
4. Under **App Extensions** → Add **Custom Panel**
   - Name: `Deal Chat`
   - Panel location: `Deal detail view`
   - iframe URL: `https://your-railway-app.railway.app/panel` 
     *(host the frontend HTML at this path or use a static host)*
   - Height: `600px`
5. Save and install the app to your Pipedrive account

---

### 3. Host Frontend

Option A — Serve from Railway backend:
- Add a route in `app.py` to serve `index.html`
- Update `BACKEND` constant in `index.html` to your Railway URL

Option B — Static host (Netlify, Vercel, GitHub Pages):
- Deploy `frontend/index.html`
- Update `BACKEND` constant in `index.html`

---

### 4. Update Frontend Config

In `frontend/index.html`, update line:
```javascript
const BACKEND = 'https://your-railway-app.railway.app';
```

---

## Getting Your Pipedrive API Token

1. Log into Pipedrive
2. Go to Settings → Personal preferences → API
3. Copy your personal API token

---

## Getting Your Company Domain

Your Pipedrive URL is `https://YOURDOMAIN.pipedrive.com`
The domain is the part before `.pipedrive.com`

---

## File Structure

```
flooring-chat/
├── backend/
│   ├── app.py              # Flask API
│   ├── database.py         # SQLite setup
│   ├── pipedrive.py        # Pipedrive API calls
│   ├── scheduler.py        # Inactivity monitoring
│   ├── requirements.txt
│   ├── railway.toml
│   └── .env.example
└── frontend/
    └── index.html          # Pipedrive panel UI
```

---

## Phase 2 (Future)

- [ ] "My Chats" filter button
- [ ] @mention notifications
- [ ] Message reactions
- [ ] File attachment support
