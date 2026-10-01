"""User Data Handler: employee CLI plus optional feedback/contribution web server."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from email import policy
from email.parser import BytesParser

try:
    from js import document  # type: ignore
    _IN_BROWSER = True
except Exception:
    _IN_BROWSER = False

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "HTML"
FEEDBACK_DIR = ROOT / "feedback"
CONTRIBUTE_DIR = ROOT / "contribute"
FEEDBACK_FILE = FEEDBACK_DIR / "feedback.txt"
CONTRIBUTE_FILE = CONTRIBUTE_DIR / "contributions.json"
DATA_LOCK = threading.Lock()

class AuthenticationError(ValueError):
    """Raised when the caller has no valid Firebase authentication token."""

class ConfigurationError(RuntimeError):
    """Raised when a required backend service is not configured."""

def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default

# Supabase Storage settings. Keep the service-role key on the backend only.
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "user-files")
SUPABASE_SIGNED_URL_SECONDS = _env_int("SUPABASE_SIGNED_URL_SECONDS", 3600, 60)
SUPABASE_MAX_FILE_BYTES = _env_int("SUPABASE_MAX_FILE_BYTES", 26214400, 1_048_576)
FIREBASE_WEB_API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "")
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*")

prompts = {
    "name": "Enter name: ",
    "employee_id": "Enter employee ID: ",
    "department": "Enter department: ",
    "salary": "Enter salary: ",
}


def ensure_data_files() -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    CONTRIBUTE_DIR.mkdir(parents=True, exist_ok=True)
    if not FEEDBACK_FILE.exists():
        FEEDBACK_FILE.write_text("", encoding="utf-8")
    if not CONTRIBUTE_FILE.exists():
        CONTRIBUTE_FILE.write_text("[]\n", encoding="utf-8")


def get_employee_info():
    employee_info = {}
    for key, prompt in prompts.items():
        value = input(prompt).strip()
        if not value:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} cannot be empty.")
        employee_info[key] = value
    return employee_info


def display_employee_info(employee_info):
    print("\nEmployee Information:")
    for key, value in employee_info.items():
        print(f"{key.replace('_', ' ').title()}: {value}")


def save_employee_info(employee_info, filename="employees.txt"):
    with open(ROOT / filename, "a", encoding="utf-8") as file:
        file.write("Employee Information:\n")
        for key, value in employee_info.items():
            file.write(f"{key.replace('_', ' ').title()}: {value}\n")
        file.write("\n")


def _clean(value, max_length):
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def save_feedback(payload: dict) -> None:
    message = _clean(payload.get("message"), 5000)
    if not message:
        raise ValueError("Feedback message is required.")
    name = _clean(payload.get("name"), 120) or "Anonymous"
    email = _clean(payload.get("email"), 254)
    user = _clean(payload.get("userEmail"), 254)
    timestamp = datetime.now(timezone.utc).isoformat()
    block = (
        "=" * 72 + "\n"
        f"Time (UTC): {timestamp}\n"
        f"Name: {name}\n"
        f"Email: {email or user or 'Not provided'}\n"
        f"Feedback:\n{message}\n"
    )
    with DATA_LOCK:
        with FEEDBACK_FILE.open("a", encoding="utf-8") as fh:
            fh.write(block)
            fh.write("\n")


def save_contribution(payload: dict) -> None:
    name = _clean(payload.get("name"), 120) or "Anonymous"
    email = _clean(payload.get("email"), 254)
    user = _clean(payload.get("userEmail"), 254)
    github = _clean(payload.get("github"), 500)
    contribution_type = _clean(payload.get("type"), 80) or "Other"
    message = _clean(payload.get("message"), 5000)
    if not message:
        raise ValueError("Contribution details are required.")

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "email": email or user,
        "github": github,
        "type": contribution_type,
        "message": message,
    }
    with DATA_LOCK:
        try:
            existing = json.loads(CONTRIBUTE_FILE.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except (OSError, json.JSONDecodeError):
            existing = []
        existing.append(entry)
        CONTRIBUTE_FILE.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _supabase_request(method: str, endpoint: str, *, body=None, content_type=None):
    if not _supabase_configured():
        raise RuntimeError("Supabase Storage is not configured on the server.")
    url = f"{SUPABASE_URL}{endpoint}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    data = body
    if content_type:
        headers["Content-Type"] = content_type
    elif isinstance(body, (dict, list)):
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif isinstance(body, str):
        data = body.encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=45) as response:
            raw = response.read()
            if not raw:
                return response.status, None
            try:
                return response.status, json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return response.status, raw
    except HTTPError as exc:
        raw = exc.read()
        detail = raw.decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"Supabase Storage returned {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase Storage connection failed: {exc.reason}") from exc


def _firebase_user_from_id_token(id_token: str) -> dict:
    if not FIREBASE_WEB_API_KEY:
        raise ConfigurationError("FIREBASE_WEB_API_KEY is not configured on the server.")
    if not id_token or len(id_token) > 12000:
        raise AuthenticationError("Missing or invalid Firebase ID token.")
    endpoint = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={quote(FIREBASE_WEB_API_KEY, safe='')}"
    body = json.dumps({"idToken": id_token}).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("error", {}).get("message", "Authentication failed")
        except json.JSONDecodeError:
            detail = "Authentication failed"
        raise AuthenticationError(detail) from exc
    except (URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not validate the Firebase session.") from exc
    users = payload.get("users") or []
    if not users or not users[0].get("localId"):
        raise AuthenticationError("Firebase session is invalid or expired.")
    return users[0]


def _safe_filename(filename: str) -> str:
    filename = Path(filename or "").name
    filename = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip(" .")
    return filename[:180] or "upload.bin"


def _extract_multipart_file(content_type: str, body: bytes):
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("File uploads must use multipart/form-data.")
    # Parse the request body as a MIME multipart message using the stdlib.
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    if not message.is_multipart():
        raise ValueError("Invalid multipart request.")
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if disposition == "form-data" and filename:
            return _safe_filename(filename), part.get_content_type(), part.get_payload(decode=True) or b""
    raise ValueError("No file was included in the upload.")


def _user_prefix(uid: str) -> str:
    return f"users/{uid}/"


def _assert_user_path(uid: str, path: str) -> str:
    path = str(path or "").lstrip("/")
    prefix = _user_prefix(uid)
    if not path.startswith(prefix) or path == prefix or ".." in Path(path).parts:
        raise ValueError("Invalid file path.")
    return path


def upload_user_file(uid: str, filename: str, content_type: str, content: bytes) -> dict:
    filename = _safe_filename(filename)
    if len(content) > SUPABASE_MAX_FILE_BYTES:
        raise ValueError(f"File is too large. Maximum allowed size is {SUPABASE_MAX_FILE_BYTES} bytes.")
    unique_name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:12]}_{filename}"
    path = f"{_user_prefix(uid)}{unique_name}"
    endpoint = f"/storage/v1/object/{quote(SUPABASE_STORAGE_BUCKET, safe='')}/{quote(path, safe='/')}"
    _supabase_request(
        "POST",
        endpoint,
        body=content,
        content_type=content_type or "application/octet-stream",
    )
    return {"name": filename, "path": path, "size": len(content), "contentType": content_type or "application/octet-stream"}


def list_user_files(uid: str) -> list[dict]:
    prefix = _user_prefix(uid)
    endpoint = f"/storage/v1/object/list/{quote(SUPABASE_STORAGE_BUCKET, safe='')}"
    _, objects = _supabase_request(
        "POST",
        endpoint,
        body={
            "prefix": prefix,
            "limit": 500,
            "offset": 0,
            "sortBy": {"column": "created_at", "order": "desc"},
        },
    )
    if not isinstance(objects, list):
        return []
    paths = []
    normalized = []
    for obj in objects:
        if not isinstance(obj, dict) or not obj.get("name"):
            continue
        name = str(obj["name"])
        path = name if name.startswith(prefix) else prefix + name
        path = _assert_user_path(uid, path)
        paths.append(path)
        metadata = obj.get("metadata") or {}
        normalized.append({
            "name": Path(path).name.split("_", 3)[-1] if "_" in Path(path).name else Path(path).name,
            "path": path,
            "size": metadata.get("size"),
            "createdAt": obj.get("created_at"),
            "updatedAt": obj.get("updated_at"),
            "contentType": metadata.get("mimetype") or metadata.get("contentType") or "application/octet-stream",
        })
    if not paths:
        return []
    _, signed = _supabase_request(
        "POST",
        f"/storage/v1/object/sign/{quote(SUPABASE_STORAGE_BUCKET, safe='')}",
        body={"paths": paths, "expiresIn": SUPABASE_SIGNED_URL_SECONDS},
    )
    signed_by_path = {}
    if isinstance(signed, list):
        for item in signed:
            if isinstance(item, dict) and item.get("path") and item.get("signedURL"):
                signed_by_path[item["path"]] = item["signedURL"]
    base = SUPABASE_URL
    for item in normalized:
        signed_path = signed_by_path.get(item["path"])
        if signed_path:
            if signed_path.startswith("http"):
                item["downloadUrl"] = signed_path
            else:
                item["downloadUrl"] = f"{base}/storage/v1{signed_path}"
            if item.get("downloadUrl"):
                separator = "&" if "?" in item["downloadUrl"] else "?"
                item["downloadUrl"] += separator + "download=" + quote(item["name"], safe="")
    return normalized


def delete_user_file(uid: str, path: str) -> None:
    path = _assert_user_path(uid, path)
    _supabase_request(
        "DELETE",
        f"/storage/v1/object/{quote(SUPABASE_STORAGE_BUCKET, safe='')}",
        body={"prefixes": [path]},
    )


class AppHandler(SimpleHTTPRequestHandler):
    """Serve HTML and accept small JSON POST requests for feedback/contributions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ALLOW_ORIGIN)
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()

    def _require_user(self):
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise AuthenticationError("Authentication is required.")
        token = authorization[7:].strip()
        return _firebase_user_from_id_token(token)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request body.") from exc
        if length <= 0 or length > 12000:
            raise ValueError("Invalid request body.")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid JSON body.") from exc
        if not isinstance(data, dict):
            raise ValueError("Request must contain a JSON object.")
        return data

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "supabaseConfigured": _supabase_configured()})
            return
        if parsed.path == "/api/files":
            try:
                if not _supabase_configured():
                    self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Supabase Storage is not configured on the server."})
                    return
                user = self._require_user()
                files = list_user_files(user["localId"])
                self._send_json(HTTPStatus.OK, {"files": files})
            except AuthenticationError as exc:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
            except ConfigurationError as exc:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/files":
            try:
                if not _supabase_configured():
                    self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Supabase Storage is not configured on the server."})
                    return
                user = self._require_user()
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > SUPABASE_MAX_FILE_BYTES + 2_000_000:
                    raise ValueError("Upload is missing or too large.")
                body = self.rfile.read(length)
                filename, content_type, content = _extract_multipart_file(self.headers.get("Content-Type", ""), body)
                saved = upload_user_file(user["localId"], filename, content_type, content)
                self._send_json(HTTPStatus.CREATED, {"ok": True, "file": saved})
            except AuthenticationError as exc:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
            except ConfigurationError as exc:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return
        if parsed.path not in {"/api/feedback", "/api/contribute"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found."})
            return
        try:
            payload = self._read_json()
            if parsed.path == "/api/feedback":
                save_feedback(payload)
            else:
                save_contribution(payload)
            self._send_json(HTTPStatus.CREATED, {"ok": True})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except OSError as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Could not save data: {exc}"})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Unexpected server error: {exc}"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/files":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found."})
            return
        try:
            if not _supabase_configured():
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Supabase Storage is not configured on the server."})
                return
            user = self._require_user()
            payload = self._read_json()
            delete_user_file(user["localId"], payload.get("path", ""))
            self._send_json(HTTPStatus.OK, {"ok": True})
        except AuthenticationError as exc:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        except ConfigurationError as exc:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def serve(host="127.0.0.1", port=8000):
    ensure_data_files()
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"User Data Handler web server running at http://{host}:{port}")
    print(f"Feedback file: {FEEDBACK_FILE}")
    print(f"Contribution file: {CONTRIBUTE_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="User Data Handler")
    parser.add_argument("--web", action="store_true", help="serve the HTML app and feedback/contribution API")
    parser.add_argument("--host", default="127.0.0.1", help="web server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="web server port (default: 8000)")
    args = parser.parse_args()

    if args.web:
        serve(args.host, args.port)
        return

    if _IN_BROWSER:
        return
    employee_info = get_employee_info()
    display_employee_info(employee_info)
    save_employee_info(employee_info)


if __name__ == "__main__":
    main()
