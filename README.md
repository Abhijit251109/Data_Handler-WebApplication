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


## Theme selection

The web UI supports **Light**, **Dark**, and **System** themes. The selected preference is stored in the browser and is shared across the login and dashboard pages. **System** follows the device/browser color-scheme preference and updates when that preference changes.
