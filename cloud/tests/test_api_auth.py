from __future__ import annotations

import unittest

from fastapi import HTTPException

from cloud.app.api.routes import require_api_token
from cloud.app.config import Settings


class ApiAuthTest(unittest.TestCase):
    def test_allows_requests_when_token_is_not_configured(self) -> None:
        require_api_token(Settings(api_token=""), None)

    def test_allows_matching_token(self) -> None:
        require_api_token(Settings(api_token="expected"), "expected")

    def test_rejects_missing_or_wrong_token(self) -> None:
        with self.assertRaises(HTTPException):
            require_api_token(Settings(api_token="expected"), None)

        with self.assertRaises(HTTPException):
            require_api_token(Settings(api_token="expected"), "wrong")


if __name__ == "__main__":
    unittest.main()
