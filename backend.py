import os
import re
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


class BackendConfigurationError(ValueError):
    pass


class ExternalServiceError(RuntimeError):
    pass


def load_settings():
    required = (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "FIREBASE_WEB_API_KEY",
        "CORS_ALLOW_ORIGIN",
    )
    settings = {name: os.environ.get(name, "").strip() for name in required}
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise BackendConfigurationError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    supabase = urlparse(settings["SUPABASE_URL"])
    if (
        supabase.scheme not in ("http", "https")
        or not supabase.netloc
        or supabase.username
        or supabase.password
        or supabase.path not in ("", "/")
        or supabase.query
        or supabase.fragment
    ):
        raise BackendConfigurationError(
            "SUPABASE_URL must be an http(s) project origin."
        )

    origin = urlparse(settings["CORS_ALLOW_ORIGIN"])
    if (
        origin.scheme not in ("http", "https")
        or not origin.netloc
        or origin.username
        or origin.password
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        raise BackendConfigurationError(
            "CORS_ALLOW_ORIGIN must contain only an http(s) origin."
        )
    settings["CORS_ALLOW_ORIGIN"] = (
        f"{origin.scheme}://{origin.netloc}".rstrip("/")
    )
    settings["SUPABASE_URL"] = settings["SUPABASE_URL"].rstrip("/")
    settings["SUPABASE_STORAGE_BUCKET"] = (
        os.environ.get("SUPABASE_STORAGE_BUCKET", "").strip() or "user-files"
    )

    for name, default in (
        ("SUPABASE_SIGNED_URL_SECONDS", "3600"),
        ("SUPABASE_MAX_FILE_BYTES", str(25 * 1024 * 1024)),
    ):
        raw_value = os.environ.get(name, default).strip()
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise BackendConfigurationError(f"{name} must be a positive integer.") from exc
        if value <= 0:
            raise BackendConfigurationError(f"{name} must be a positive integer.")
        settings[name] = value

    return settings


def create_app(settings=None):
    settings = settings or load_settings()
    app = Flask(__name__)
    app.config.update(settings)
    app.config["MAX_CONTENT_LENGTH"] = settings["SUPABASE_MAX_FILE_BYTES"] + 1024 * 1024

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin:
            response.headers.add("Vary", "Origin")
        if origin == app.config["CORS_ALLOW_ORIGIN"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type"
            )
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    @app.before_request
    def reject_unapproved_origins():
        origin = request.headers.get("Origin")
        if origin and origin != app.config["CORS_ALLOW_ORIGIN"]:
            return jsonify(error="Origin is not allowed."), 403

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(ExternalServiceError)
    def external_service_error(error):
        app.logger.warning("%s", error)
        return jsonify(error="A required external service is unavailable."), 502

    def authenticate_request():
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None, (jsonify(error="A Firebase bearer token is required."), 401)

        try:
            response = requests.post(
                "https://identitytoolkit.googleapis.com/v1/accounts:lookup",
                params={"key": app.config["FIREBASE_WEB_API_KEY"]},
                json={"idToken": token.strip()},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise ExternalServiceError(
                "Firebase token validation request failed."
            ) from exc

        if response.status_code in (400, 401, 403):
            return None, (jsonify(error="The Firebase token is invalid or expired."), 401)
        if response.status_code != 200:
            raise ExternalServiceError(
                f"Firebase token validation returned HTTP {response.status_code}."
            )

        try:
            users = response.json().get("users", [])
        except (AttributeError, ValueError) as exc:
            raise ExternalServiceError(
                "Firebase returned an invalid token response."
            ) from exc
        if (
            not isinstance(users, list)
            or not users
            or not isinstance(users[0], dict)
        ):
            return None, (jsonify(error="The Firebase token is invalid or expired."), 401)
        uid = users[0].get("localId")
        if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", uid):
            return None, (jsonify(error="The Firebase token is invalid or expired."), 401)
        return uid, None

    def storage_headers(content_type="application/json"):
        service_key = app.config["SUPABASE_SERVICE_ROLE_KEY"]
        return {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": content_type,
        }

    def storage_url(endpoint):
        bucket = quote(app.config["SUPABASE_STORAGE_BUCKET"], safe="")
        return f"{app.config['SUPABASE_URL']}/storage/v1/{endpoint.format(bucket=bucket)}"

    def storage_request(method, url, **kwargs):
        headers = kwargs.pop("headers", storage_headers())
        try:
            response = requests.request(
                method, url, headers=headers, timeout=30, **kwargs
            )
        except requests.RequestException as exc:
            raise ExternalServiceError("Supabase Storage request failed.") from exc
        if not response.ok:
            raise ExternalServiceError(
                f"Supabase Storage returned HTTP {response.status_code}."
            )
        return response

    @app.route("/api/health", methods=["GET", "OPTIONS"])
    def health():
        if request.method == "OPTIONS":
            return "", 204
        return jsonify(status="ok")

    @app.route("/api/files", methods=["GET", "POST", "DELETE", "OPTIONS"])
    def files():
        if request.method == "OPTIONS":
            return "", 204

        uid, error = authenticate_request()
        if error:
            return error

        bucket = quote(app.config["SUPABASE_STORAGE_BUCKET"], safe="")
        user_prefix = f"users/{uid}"

        if request.method == "POST":
            uploaded_file = request.files.get("file")
            if uploaded_file is None or not uploaded_file.filename:
                return jsonify(error="Choose a file to upload."), 400

            content = uploaded_file.stream.read(
                app.config["SUPABASE_MAX_FILE_BYTES"] + 1
            )
            if len(content) > app.config["SUPABASE_MAX_FILE_BYTES"]:
                return jsonify(error="The file exceeds the configured size limit."), 413

            original_name = unicodedata.normalize(
                "NFKC", uploaded_file.filename.replace("\\", "/").split("/")[-1]
            )
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name).strip("._")
            safe_name = (safe_name or "upload")[:120]
            object_path = f"{user_prefix}/{uuid.uuid4().hex}_{safe_name}"
            encoded_path = quote(object_path, safe="/")
            storage_request(
                "POST",
                storage_url(f"object/{bucket}/{encoded_path}"),
                data=content,
                headers=storage_headers(
                    uploaded_file.mimetype or "application/octet-stream"
                ),
            )
            return jsonify(file={"name": safe_name, "path": object_path}), 201

        if request.method == "GET":
            list_response = storage_request(
                "POST",
                storage_url(f"object/list/{bucket}"),
                json={
                    "prefix": f"{user_prefix}/",
                    "limit": 1000,
                    "offset": 0,
                    "sortBy": {"column": "name", "order": "asc"},
                },
            )
            try:
                objects = list_response.json()
            except ValueError as exc:
                raise ExternalServiceError("Supabase returned an invalid file list.") from exc
            if not isinstance(objects, list):
                raise ExternalServiceError("Supabase returned an invalid file list.")

            result = []
            for item in objects:
                name = item.get("name")
                if not isinstance(name, str) or not name or "/" in name:
                    continue
                object_path = f"{user_prefix}/{name}"
                sign_response = storage_request(
                    "POST",
                    storage_url(
                        f"object/sign/{bucket}/{quote(object_path, safe='/')}"
                    ),
                    json={"expiresIn": app.config["SUPABASE_SIGNED_URL_SECONDS"]},
                )
                try:
                    signed_url = sign_response.json().get("signedURL")
                except (AttributeError, ValueError) as exc:
                    raise ExternalServiceError(
                        "Supabase returned an invalid signed URL."
                    ) from exc
                if not isinstance(signed_url, str) or not signed_url:
                    raise ExternalServiceError("Supabase returned an invalid signed URL.")
                if signed_url.startswith("/"):
                    signed_url = (
                        f"{app.config['SUPABASE_URL']}/storage/v1{signed_url}"
                        if not signed_url.startswith("/storage/v1/")
                        else f"{app.config['SUPABASE_URL']}{signed_url}"
                    )
                elif not signed_url.startswith(("https://", "http://")):
                    signed_url = (
                        f"{app.config['SUPABASE_URL']}/storage/v1/{signed_url.lstrip('/')}"
                    )
                metadata = item.get("metadata") or {}
                result.append(
                    {
                        "name": name.split("_", 1)[-1],
                        "path": object_path,
                        "size": metadata.get("size"),
                        "created_at": item.get("created_at"),
                        "url": signed_url,
                    }
                )
            return jsonify(files=result)

        body = request.get_json(silent=True)
        object_path = body.get("path") if isinstance(body, dict) else None
        path_pattern = re.compile(
            rf"^users/{re.escape(uid)}/[0-9a-f]{{32}}_[A-Za-z0-9._-]{{1,120}}$"
        )
        if not isinstance(object_path, str) or not path_pattern.fullmatch(object_path):
            return jsonify(error="A valid file path is required."), 400

        storage_request(
            "DELETE",
            storage_url(f"object/{bucket}"),
            json={"prefixes": [object_path]},
        )
        return jsonify(deleted=True)

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify(error="The uploaded file exceeds the configured size limit."), 413

    return app


if __name__ == "__main__":
    from waitress import serve

    port = int(os.environ.get("PORT", "8000"))
    serve(create_app(), host="0.0.0.0", port=port)
