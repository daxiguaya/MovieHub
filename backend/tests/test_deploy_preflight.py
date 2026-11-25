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

    def test_rejects_default_routes(self):
        for value in ("0.0.0.0/0", "::/0"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "default route"):
                    PREFLIGHT.validate_trusted_proxy_ips(value)

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


class RolloutMigrationSafetyTests(unittest.TestCase):
    def test_schema_migration_runs_after_backup_and_before_backend_restart(self):
        script_path = Path(__file__).resolve().parents[2] / "deploy" / "rollout_online_discovery.sh"
        script = script_path.read_text(encoding="utf-8")
        backup = script.index("source.backup(target)")
        main_flow_start = script.index('ROLLBACK_DB_BACKUP="$BACKUP_PATH')
        main_flow = script[main_flow_start:]
        stop_backend = main_flow.index("docker compose stop moviehub")
        migrate = main_flow.index("docker compose run --rm --no-deps -T --name \"moviehub-schema-migrate-$STAMP\" moviehub python -m scripts.migrate")
        start_backend = main_flow.index("docker compose up -d --no-deps moviehub moviehub-web")
        self.assertLess(backup, main_flow_start)
        self.assertLess(stop_backend, migrate)
        self.assertLess(migrate, start_backend)

    def test_rollback_restores_database_before_restarting_previous_images(self):
        script_path = Path(__file__).resolve().parents[2] / "deploy" / "rollout_online_discovery.sh"
        script = script_path.read_text(encoding="utf-8")
        rollback_start = script.index("rollback() {")
        rollback_end = script.index("\non_exit() {", rollback_start)
        rollback = script[rollback_start:rollback_end]
        self.assertIn("source.backup(target)", rollback)
        self.assertLess(rollback.index("source.backup(target)"), rollback.index('docker tag "$ROLLBACK_BACKEND"'))
        self.assertIn('docker compose up -d --no-deps moviehub moviehub-web', rollback)

    def test_rollback_restores_discovery_cache_before_previous_images(self):
        script_path = Path(__file__).resolve().parents[2] / "deploy" / "rollout_online_discovery.sh"
        script = script_path.read_text(encoding="utf-8")
        rollback_start = script.index("rollback() {")
        rollback_end = script.index("\\non_exit() {", rollback_start)
        rollback = script[rollback_start:rollback_end]
        self.assertIn('ROLLBACK_DISCOVERY_DB_BACKUP="$BACKUP_PATH/online-discovery-rollout-$STAMP/discovery.sqlite3"', script)
        self.assertIn("Restored pre-rollout discovery cache (including external favorites)", rollback)
        self.assertIn('rm -f "$DATA_PATH/cache/discovery.sqlite3"', rollback)
        self.assertLess(
            rollback.index("Restored pre-rollout discovery cache (including external favorites)"),
            rollback.index('docker tag "$ROLLBACK_BACKEND"'),
        )

    def test_npm_uses_graceful_reload_not_container_restart(self):
        script_path = Path(__file__).resolve().parents[2] / "deploy" / "rollout_online_discovery.sh"
        script = script_path.read_text(encoding="utf-8")
        self.assertIn("nginx -s reload", script)
        self.assertNotIn("docker restart nginx-proxy-manager", script)
        self.assertNotIn("docker compose restart nginx-proxy-manager", script)
