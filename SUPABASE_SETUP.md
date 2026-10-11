# Supabase Storage setup for User Data Handler

The dashboard's **Saved files** feature uses a private Supabase Storage bucket. The browser never receives the Supabase service-role key.

## 1. Create the bucket

In the Supabase Dashboard:

1. Open **Storage**.
2. Create a bucket named `user-files`.
3. Keep the bucket **Private**.

The application creates file paths like:

```text
users/<firebase-user-uid>/<unique-file-name>
```

This makes the file library account-specific.

## 2. Configure the Python backend

The backend loads `.env` from the repository root for local development. Keep
your existing `.env` and confirm it has the values below; for a fresh checkout,
copy `.env.example` to `.env` first. `.env` is ignored by Git. For deployment,
set the same variables in the backend host's environment settings.

```text
SUPABASE_URL=https://kyivphipxjuiyukvakez.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET=user-files
SUPABASE_SIGNED_URL_SECONDS=3600
SUPABASE_MAX_FILE_BYTES=26214400
FIREBASE_WEB_API_KEY=YOUR_FIREBASE_WEB_API_KEY
CORS_ALLOW_ORIGIN=https://YOUR-FRONTEND-DOMAIN
```

`SUPABASE_SERVICE_ROLE_KEY` must stay on the server. Do not add it to
`HTML/app-config.js` or any frontend JavaScript.

The frontend may contain `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in `HTML/app-config.js`. These are public configuration values. They are not a replacement for the backend service-role key used by the current Storage API.

## 3. Configure the frontend

`HTML/app-config.js` contains the public Supabase project URL and publishable key, plus the backend URL setting:

```javascript
window.SUPABASE_URL = 'https://kyivphipxjuiyukvakez.supabase.co';
window.SUPABASE_PUBLISHABLE_KEY = 'YOUR_SUPABASE_PUBLISHABLE_KEY';
```

The backend URL setting is:

```javascript
window.APP_API_BASE_URL = 'https://YOUR-BACKEND.example.com';
```

When the frontend and Python API are deployed on the same origin, it can remain an empty string.

## 4. Start locally

```bash
pip install -r requirements.txt
python backend.py
```

In a second terminal, serve the static frontend:

```bash
python -m http.server 5500 --directory HTML
```

For this local setup, set `CORS_ALLOW_ORIGIN=http://localhost:5500` in `.env`
and set `window.APP_API_BASE_URL = 'http://localhost:8000';` in
`HTML/app-config.js`. Open `http://localhost:5500` and sign in.

For a deployed frontend, set `CORS_ALLOW_ORIGIN` to its exact origin (scheme
and domain, without a path), and set `window.APP_API_BASE_URL` in
`HTML/app-config.js` to the deployed backend URL. Static hosting cannot read
the server's `.env`; only the public backend URL belongs in frontend config.

## 5. What happens when a user uploads a file

The dashboard gets the Firebase ID token for the currently signed-in user and sends the file to `POST /api/files`.

The backend validates that Firebase token with Firebase Authentication, obtains the user's Firebase UID, and only then stores the file under that UID's Supabase Storage prefix.

When the dashboard is opened again, `GET /api/files` lists that user's objects and returns short-lived signed URLs. This is why the user can find the same saved files from another device after signing into the same Firebase account.

## 6. File endpoints

```text
GET    /api/files      List the current user's saved files and signed URLs
POST   /api/files      Upload a multipart form file field named "file"
DELETE /api/files      Delete JSON {"path":"<returned file path>"}
GET    /api/health     Backend health check
```

All file routes except health require a Firebase ID token in the
`Authorization: Bearer <token>` header. No browser local storage is used as the
source of truth for saved files.

## Production persistence note

The Supabase `user-files` bucket is the source of truth for the dashboard's saved-file library, so the same Firebase account can access those files across devices. The `feedback/feedback.txt` and `contribute/contributions.json` files are separate backend files and are not automatically made durable by this Storage integration. If your backend runs on an ephemeral filesystem, use a durable database/object-storage mirror for those two records as well.
