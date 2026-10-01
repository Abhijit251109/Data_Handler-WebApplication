# User Data Handler

A small Firebase-authenticated employee data application with a Python CLI and a static web dashboard.

## Web app

The dashboard uses Firebase Authentication and Cloud Firestore. After enabling **Email/Password** authentication and creating a Firestore database in the Firebase project, deploy the included `firestore.rules` to protect records so authenticated users can only access their own records.

With Firebase CLI:

```bash
firebase deploy --only firestore:rules
```

Then host the `HTML/` directory with GitHub Pages or another static host and add that host domain to Firebase Authentication's authorized domains.

## Python CLI

Run:

```bash
python main.py
```

The CLI validates required fields and appends records to `employees.txt`.

## Data safety

`employees.txt` is ignored by Git. Do not commit employee or other personal data to the repository. Firebase web API keys are not passwords, but Firestore security rules and Authentication configuration must be set correctly.

## Authentication troubleshooting

The web login uses the Firebase project `user-data-handler`. The login page now includes a password-reset flow and shows the Firebase error category instead of treating every authentication/configuration failure as a bad password.

In Firebase Console, verify that **Authentication → Sign-in method → Email/Password** is enabled and that the deployed website's domain is present under the Authentication authorized domains. These settings are required for email/password authentication. See the Firebase documentation for the provider setup. 


## Feedback and contribution forms

The login page and dashboard include **Feedback** and **Contribute** buttons. They submit to the Python web server:

```bash
python main.py --web
```

The server serves the `HTML/` directory and exposes:

- `POST /api/feedback` → appends submissions to `./feedback/feedback.txt`
- `POST /api/contribute` → appends submissions to `./contribute/contributions.json`
- `GET /api/health` → simple health check

Open `http://127.0.0.1:8000/` after starting the server. The Firebase login/dashboard functionality remains unchanged.

### Contact links

Project GitHub: https://github.com/Abhijit251109/Data_Handler-WebApplication  
Email: abhijitschool036@gmail.com

### Hosting note

A static host such as GitHub Pages can serve the HTML pages, but it cannot run the Python API or persist files on the server. To actually save feedback/contribution data, deploy `main.py` (or another backend implementing the same endpoints) on a server and configure the frontend API URL for that deployment.


## Persistent saved files with Supabase Storage

The dashboard includes a **Saved files** section. When a signed-in user uploads a file, the Python backend validates the Firebase ID token and stores the file in a private Supabase Storage bucket under:

```text
users/<firebase-user-uid>/<unique-file-name>
```

That means the same Firebase account can sign in from another browser/device and see the same saved-file library. Firebase already provides the same cross-device behavior for the employee records in Firestore.

### Supabase setup

Create a **private** Storage bucket named `user-files` in your Supabase project. Supabase private buckets are accessed using signed URLs or authenticated requests rather than public URLs. 

Configure these backend environment variables:

```text
SUPABASE_URL=https://kyivphipxjuiyukvakez.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET=user-files
SUPABASE_SIGNED_URL_SECONDS=3600
SUPABASE_MAX_FILE_BYTES=26214400
FIREBASE_WEB_API_KEY=YOUR_FIREBASE_WEB_API_KEY
CORS_ALLOW_ORIGIN=https://YOUR-FRONTEND-DOMAIN
```

Do **not** put `SUPABASE_SERVICE_ROLE_KEY` in `HTML/app-config.js`, the frontend JavaScript, or a public repository. It belongs only in the backend/Render environment.

`HTML/app-config.js` may contain the Supabase publishable key because it is intended for public client-side use.

For local development, copy `.env.example` to `.env` and fill in the backend-only secrets. Never commit `.env` or place `SUPABASE_SERVICE_ROLE_KEY` in frontend code.

Start locally with:

```bash
python main.py --web
```

Then set `window.APP_API_BASE_URL` in `HTML/app-config.js` to the deployed backend URL when the frontend is hosted separately on GitHub Pages.

The file API is:

```text
GET    /api/files      list this user's saved files
POST   /api/files      save a new file
DELETE /api/files      delete one of this user's files
```

The backend uses the Firebase Auth REST `accounts:lookup` endpoint to validate the current Firebase ID token and obtain the account UID before touching that user's Supabase Storage path. Firebase documents this endpoint as the way to retrieve the account associated with an ID token. 

## Audit / production deployment notes

The current build has been checked for Python syntax, browser-module syntax, HTML structure, API smoke behavior, path traversal, Firebase-auth error handling, and mocked Supabase Storage upload/list/delete behavior.

Employee records are now queried with `ownerUid == request.auth.uid`, matching `firestore.rules`. Firestore Security Rules are not filters, so an unrestricted collection query would otherwise be rejected.

The GitHub Pages workflow deploys only `HTML/`. It does not run `main.py`. Therefore `main.py` must be deployed separately (for example on Render) and `HTML/app-config.js` must point to that backend.

The `feedback/feedback.txt` and `contribute/contributions.json` files are server-side files. On hosting platforms with ephemeral filesystems, such as many free web-service plans, those files are not durable across instance replacement/redeploy. The Supabase Storage integration makes **saved user files** durable across devices; it does not currently make feedback/contribution files durable. For durable production feedback/contribution storage, mirror those records to a database or object store.

The Firebase browser SDK imports are pinned consistently to the current modular CDN version documented by Firebase at the time of this audit.
