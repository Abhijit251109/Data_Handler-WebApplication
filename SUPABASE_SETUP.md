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

Set these variables on the backend (for example, Render Environment Variables):

```text
SUPABASE_URL=https://kyivphipxjuiyukvakez.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET=user-files
SUPABASE_SIGNED_URL_SECONDS=3600
SUPABASE_MAX_FILE_BYTES=26214400
FIREBASE_WEB_API_KEY=YOUR_FIREBASE_WEB_API_KEY
CORS_ALLOW_ORIGIN=https://YOUR-FRONTEND-DOMAIN
```

`SUPABASE_SERVICE_ROLE_KEY` must stay on the server. Do not add it to `HTML/app-config.js` or any frontend JavaScript. The key you supplied should be entered only as the backend/Render environment variable `SUPABASE_SERVICE_ROLE_KEY`.

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
python main.py --web
```

Then open the dashboard and sign in.

## 5. What happens when a user uploads a file

The dashboard gets the Firebase ID token for the currently signed-in user and sends the file to `POST /api/files`.

The backend validates that Firebase token with Firebase Authentication, obtains the user's Firebase UID, and only then stores the file under that UID's Supabase Storage prefix.

When the dashboard is opened again, `GET /api/files` lists that user's objects and returns short-lived signed URLs. This is why the user can find the same saved files from another device after signing into the same Firebase account.

## 6. File endpoints

```text
GET    /api/files      List the current user's saved files
POST   /api/files      Upload a file for the current user
DELETE /api/files      Delete one of the current user's files
GET    /api/health     Backend health/configuration check
```

No browser local storage is used as the source of truth for saved files.

## Production persistence note

The Supabase `user-files` bucket is the source of truth for the dashboard's saved-file library, so the same Firebase account can access those files across devices. The `feedback/feedback.txt` and `contribute/contributions.json` files are separate backend files and are not automatically made durable by this Storage integration. If your backend runs on an ephemeral filesystem, use a durable database/object-storage mirror for those two records as well.
