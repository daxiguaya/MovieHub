#!/usr/bin/env python3
"""Read-only MovieHub deployment preflight for Synology/Linux hosts.

This script never creates directories, changes ownership, starts/stops containers,
initializes a database, edits NPM, or changes Docker networks.
"""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
COMPOSE_FILE = ROOT / "docker-compose.yml"
EXPECTED_NETWORK = "chatgpt-browser_default"
EXPECTED_CONTAINERS = {"moviehub-backend", "moviehub-web"}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def docker_json(args: list[str]):
    result = run(["docker", *args])
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "docker command failed")
    return json.loads(result.stdout)


def target_write_bit(path: Path, uid: int, gid: int) -> bool | None:
    """Check write+search mode bits for the configured UID/GID.

    This is deliberately advisory: DSM ACLs and supplementary group membership
    can change the effective result and must be checked on the NAS.
    """
    try:
        info = path.stat()
    except OSError:
        return None
    mode = info.st_mode
    if info.st_uid == uid:
        required = 0o300  # write + execute/search for owner
    elif info.st_gid == gid:
        required = 0o030  # write + execute/search for group
    else:
        required = 0o003  # write + execute/search for others
    return (mode & required) == required


def validate_trusted_proxy_ips(value: str) -> list[str]:
    """Validate Uvicorn's comma-separated IP/CIDR trust list; never allow '*'. """
    entries = [entry.strip() for entry in value.split(",") if entry.strip()]
    if not entries:
        raise ValueError("MOVIEHUB_TRUSTED_PROXY_IPS must contain at least one IP/CIDR.")
    if "*" in entries:
        raise ValueError("MOVIEHUB_TRUSTED_PROXY_IPS must never be '*'; use an exact proxy IP or subnet.")
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise ValueError(
                f"Invalid MOVIEHUB_TRUSTED_PROXY_IPS entry: {entry!r}; use an IP address or CIDR."
            ) from exc
        if network.prefixlen == 0:
            raise ValueError(
                "MOVIEHUB_TRUSTED_PROXY_IPS must not contain a default route (0.0.0.0/0 or ::/0); use the exact proxy IP or its dedicated subnet."
            )
    return entries


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    print("MovieHub read-only deployment preflight")
    print(f"Project: {ROOT}")
    print("No files, containers, networks, databases or NPM settings will be changed.\n")

    if shutil.which("docker") is None:
        print("[FAIL] docker CLI not found")
        return 2

    compose = run(["docker", "compose", "version"])
    if compose.returncode:
        errors.append("Docker Compose v2 plugin is unavailable (docker compose).")
    else:
        print(f"[OK] {compose.stdout.strip()}")

    if not COMPOSE_FILE.is_file():
        errors.append("docker-compose.yml is missing.")
    if not ENV_FILE.is_file():
        errors.append("Project-root .env is missing; copy deploy/.env.example and configure it.")
    env = load_env(ENV_FILE)
    if ENV_FILE.is_file() and (ENV_FILE.stat().st_mode & 0o077):
        warnings.append("Project .env is readable by group/others; restrict it (for example chmod 600 .env) because it contains the API key.")

    api_key = env.get("MOVIEHUB_API_KEY", "")
    if len(api_key) < 32 or re.search(r"replace|changeme|example|placeholder", api_key, re.I):
        errors.append("MOVIEHUB_API_KEY is missing, a placeholder, or shorter than 32 characters.")
    else:
        print("[OK] API key is present (value deliberately not displayed).")

    trusted_proxy_ips = env.get("MOVIEHUB_TRUSTED_PROXY_IPS", "127.0.0.1")
    try:
        validate_trusted_proxy_ips(trusted_proxy_ips)
        if trusted_proxy_ips.strip() == "127.0.0.1":
            warnings.append("MOVIEHUB_TRUSTED_PROXY_IPS still trusts loopback only; set the exact NPM IP or a dedicated subnet after confirming the NPM container.")
        else:
            print("[OK] Forwarded-header trust list contains valid explicit IP/CIDR entries.")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        uid = int(env.get("MOVIEHUB_UID", "10001"))
        gid = int(env.get("MOVIEHUB_GID", "10001"))
    except ValueError:
        uid, gid = 10001, 10001
        errors.append("MOVIEHUB_UID and MOVIEHUB_GID must be integers.")

    for key, default in (
        ("MOVIEHUB_DATA_PATH", "/volume1/docker/moviehub/data"),
        ("MOVIEHUB_BACKUP_PATH", "/volume1/backup/moviehub"),
    ):
        path = Path(env.get(key, default)).expanduser()
        if not path.is_dir():
            errors.append(f"{key} directory does not exist: {path} (preflight will not create it).")
            continue
        writable = target_write_bit(path, uid, gid)
        if writable is False:
            warnings.append(f"{key} mode bits do not show write access for UID/GID {uid}:{gid}; inspect DSM ACLs or adjust ownership before deployment: {path}")
        elif writable is None:
            errors.append(f"Cannot inspect {key}: {path}")
        else:
            print(f"[OK] {key}: exists; mode bits appear writable for {uid}:{gid} (verify DSM ACLs too).")

    frontend_config = Path(env.get("MOVIEHUB_FRONTEND_CONFIG_PATH", "./deploy/frontend-config.json"))
    if not frontend_config.is_absolute():
        frontend_config = ROOT / frontend_config
    try:
        config = json.loads(frontend_config.read_text(encoding="utf-8"))
        url = config.get("xiaoyaSearchBaseUrl", "")
        if url and not re.match(r"^https?://", url):
            errors.append("xiaoyaSearchBaseUrl must be empty or an http(s) URL.")
        else:
            print("[OK] Frontend runtime config is valid JSON.")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Frontend runtime config cannot be read/parsed: {exc}")

    compose_config = run(["docker", "compose", "config", "--format", "json"])
    if compose_config.returncode:
        errors.append("docker compose config validation failed: " + compose_config.stderr.strip())
    else:
        try:
            rendered = json.loads(compose_config.stdout)
            services = rendered.get("services", {})
            for service_name in ("moviehub", "moviehub-web"):
                service = services.get(service_name)
                if service is None:
                    errors.append(f"Compose service is missing: {service_name}")
                elif service.get("ports"):
                    errors.append(f"{service_name} publishes host ports; remove host port bindings before deployment.")
                elif not service.get("read_only"):
                    errors.append(f"{service_name} must use a read-only root filesystem.")
            if not errors:
                print("[OK] Compose config validates; both app services have no published host ports and use read-only roots.")
        except (json.JSONDecodeError, AttributeError) as exc:
            errors.append(f"Cannot inspect rendered Compose configuration: {exc}")

    try:
        network = docker_json(["network", "inspect", EXPECTED_NETWORK])[0]
        print(f"[OK] External NPM network exists: {EXPECTED_NETWORK}")
        npm_candidates = []
        for container_id, details in (network.get("Containers") or {}).items():
            name = details.get("Name", "")
            ipv4 = details.get("IPv4Address", "").split("/")[0]
            if "proxy" in name.lower() or "npm" in name.lower():
                npm_candidates.append((name, ipv4))
        if npm_candidates:
            for name, ip in npm_candidates:
                print(f"[INFO] Possible NPM network member: {name} ({ip or 'IP unavailable'})")
        else:
            warnings.append("No container name containing 'proxy' or 'npm' was identified on the shared network; verify the NPM container and its IP manually.")
    except (RuntimeError, IndexError, json.JSONDecodeError) as exc:
        errors.append(f"Cannot inspect required Docker network {EXPECTED_NETWORK}: {exc}")

    try:
        result = run(["docker", "ps", "-a", "--format", "{{.Names}}"])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "docker ps failed")
        existing = [name.strip() for name in result.stdout.splitlines() if name.strip()]
        conflicts = sorted(EXPECTED_CONTAINERS.intersection(existing))
        if conflicts:
            errors.append("Container-name conflicts exist: " + ", ".join(conflicts))
        else:
            print("[OK] No existing MovieHub container-name conflicts.")
    except (RuntimeError, json.JSONDecodeError) as exc:
        errors.append(f"Cannot inspect existing containers: {exc}")

    for item in warnings:
        print("[WARN] " + item)
    for item in errors:
        print("[FAIL] " + item)

    print(f"\nResult: {len(errors)} blocking issue(s), {len(warnings)} warning(s).")
    if errors:
        print("Do not build/start MovieHub until blocking issues are resolved.")
        return 1
    print("Static/host preflight passed. This does NOT initialize the database or deploy the application.")
    print("Before deployment, separately verify NPM route rules, TLS/access controls, import endpoint denial, and backup restore readiness.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
