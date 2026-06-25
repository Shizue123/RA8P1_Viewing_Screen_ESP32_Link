from __future__ import annotations

import unittest

from cloud.app.security import ApiRateLimiter, build_script_signature


class ScriptSignatureTest(unittest.TestCase):
    def test_signature_is_stable(self) -> None:
        signature = build_script_signature(
            "secret",
            "req_1",
            "script_1",
            "threshold_control",
            "sha256:abc",
            123456,
            "ra8p1_demo_001",
        )
        self.assertEqual(len(signature), 64)
        self.assertEqual(
            signature,
            build_script_signature(
                "secret",
                "req_1",
                "script_1",
                "threshold_control",
                "sha256:abc",
                123456,
                "ra8p1_demo_001",
            ),
        )


class ApiRateLimiterTest(unittest.TestCase):
    def test_rate_limiter_blocks_after_limit(self) -> None:
        limiter = ApiRateLimiter()
        self.assertTrue(limiter.allow("client:/agent/deploy", 2, 60))
        self.assertTrue(limiter.allow("client:/agent/deploy", 2, 60))
        self.assertFalse(limiter.allow("client:/agent/deploy", 2, 60))


if __name__ == "__main__":
    unittest.main()
