import io
import unittest
from unittest.mock import Mock, patch

from backend import create_app


def make_settings():
    return {
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "server-secret",
        "FIREBASE_WEB_API_KEY": "firebase-api-key",
        "CORS_ALLOW_ORIGIN": "https://frontend.example",
        "SUPABASE_STORAGE_BUCKET": "user-files",
        "SUPABASE_SIGNED_URL_SECONDS": 3600,
        "SUPABASE_MAX_FILE_BYTES": 1024,
    }


def response(status_code, body):
    result = Mock()
    result.status_code = status_code
    result.ok = 200 <= status_code < 300
    result.json.return_value = body
    return result


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(make_settings())
        self.client = self.app.test_client()
        self.auth_header = {"Authorization": "Bearer firebase-id-token"}

    @patch("backend.requests.post")
    def test_upload_authenticates_then_stores_under_user_path(self, post):
        post.return_value = response(200, {"users": [{"localId": "user-123"}]})
        with patch("backend.requests.request", return_value=response(200, {})) as storage:
            result = self.client.post(
                "/api/files",
                data={"file": (io.BytesIO(b"file-content"), "report!.txt")},
                headers=self.auth_header,
                content_type="multipart/form-data",
            )

        self.assertEqual(result.status_code, 201)
        saved = result.get_json()["file"]
        self.assertEqual(saved["name"], "report_.txt")
        self.assertRegex(saved["path"], r"^users/user-123/[0-9a-f]{32}_report_\.txt$")
        self.assertIn("/storage/v1/object/user-files/", storage.call_args.args[1])
        self.assertEqual(storage.call_args.kwargs["data"], b"file-content")
        self.assertEqual(
            storage.call_args.kwargs["headers"]["Authorization"],
            "Bearer server-secret",
        )

    @patch("backend.requests.post")
    def test_lists_only_authenticated_user_files_with_signed_links(self, post):
        post.return_value = response(200, {"users": [{"localId": "user-123"}]})
        signed_path = (
            "/object/sign/user-files/users/user-123/"
            "0123456789abcdef0123456789abcdef_photo.png?token=temporary"
        )
        with patch(
            "backend.requests.request",
            side_effect=[
                response(
                    200,
                    [
                        {
                            "name": "0123456789abcdef0123456789abcdef_photo.png",
                            "metadata": {"size": 42},
                            "created_at": "2026-10-11T00:00:00Z",
                        }
                    ],
                ),
                response(200, {"signedURL": signed_path}),
            ],
        ) as storage:
            result = self.client.get("/api/files", headers=self.auth_header)

        self.assertEqual(result.status_code, 200)
        file_item = result.get_json()["files"][0]
        self.assertEqual(file_item["name"], "photo.png")
        self.assertEqual(file_item["size"], 42)
        self.assertEqual(
            file_item["url"],
            "https://project.supabase.co/storage/v1" + signed_path,
        )
        self.assertEqual(storage.call_count, 2)
        self.assertEqual(
            storage.call_args_list[0].kwargs["json"]["prefix"], "users/user-123/"
        )

    @patch("backend.requests.post")
    def test_delete_rejects_paths_outside_the_authenticated_user(self, post):
        post.return_value = response(200, {"users": [{"localId": "user-123"}]})
        with patch("backend.requests.request") as storage:
            result = self.client.delete(
                "/api/files",
                json={"path": "users/another-user/" + "a" * 32 + "_private.txt"},
                headers=self.auth_header,
            )

        self.assertEqual(result.status_code, 400)
        storage.assert_not_called()

    @patch("backend.requests.post")
    def test_missing_bearer_token_is_rejected(self, post):
        result = self.client.get("/api/files")

        self.assertEqual(result.status_code, 401)
        post.assert_not_called()

    def test_unapproved_origin_is_rejected(self):
        result = self.client.options(
            "/api/files",
            headers={"Origin": "https://attacker.example"},
        )

        self.assertEqual(result.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", result.headers)

    def test_health_endpoint_does_not_disclose_configuration(self):
        result = self.client.get(
            "/api/health",
            headers={"Origin": "https://frontend.example"},
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json(), {"status": "ok"})
        self.assertEqual(
            result.headers["Access-Control-Allow-Origin"],
            "https://frontend.example",
        )

    @patch("backend.requests.post")
    def test_upload_rejects_files_over_the_configured_limit(self, post):
        post.return_value = response(200, {"users": [{"localId": "user-123"}]})
        with patch("backend.requests.request") as storage:
            result = self.client.post(
                "/api/files",
                data={"file": (io.BytesIO(b"x" * 1025), "large.bin")},
                headers=self.auth_header,
                content_type="multipart/form-data",
            )

        self.assertEqual(result.status_code, 413)
        storage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
