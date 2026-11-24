"""Unit tests for the standalone Synology deployment preflight."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


PREFLIGHT_PATH = Path(__file__).resolve().parents[2] / "deploy" / "preflight.py"
SPEC = importlib.util.spec_from_file_location("moviehub_deploy_preflight", PREFLIGHT_PATH)
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


class TrustedProxyValidationTests(unittest.TestCase):
    def test_accepts_single_ip_and_cidr_list(self):
        self.assertEqual(
            PREFLIGHT.validate_trusted_proxy_ips("172.20.0.3, 172.20.0.0/24"),
            ["172.20.0.3", "172.20.0.0/24"],
        )

    def test_rejects_wildcard(self):
        with self.assertRaisesRegex(ValueError, "never be '\*'"):
            PREFLIGHT.validate_trusted_proxy_ips("*")

    def test_rejects_empty_value(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            PREFLIGHT.validate_trusted_proxy_ips(" , ")

    def test_rejects_invalid_hostname(self):
        with self.assertRaisesRegex(ValueError, "Invalid"):
            PREFLIGHT.validate_trusted_proxy_ips("npm-proxy")


class DirectoryPermissionTests(unittest.TestCase):
    def test_requires_write_and_search_bits_for_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            os.chmod(path, 0o200)
            self.assertFalse(
                PREFLIGHT.target_write_bit(path, os.getuid(), os.getgid())
            )
            os.chmod(path, 0o300)
            self.assertTrue(
                PREFLIGHT.target_write_bit(path, os.getuid(), os.getgid())
            )


if __name__ == "__main__":
    unittest.main()
