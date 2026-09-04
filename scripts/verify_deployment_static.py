"""Static, daemon-free validation for the Module 10 deployment assets."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    def check(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append(name)

    files = {
        "compose.yaml",
        ".env.example",
        ".dockerignore",
        ".gitignore",
        "docker/backend/Dockerfile",
        "docker/worker/Dockerfile",
        "docker/worker/healthcheck.py",
        "docker/lreca/Dockerfile",
        "docker/frontend/Dockerfile",
        "docker/caddy/Caddyfile",
        "docker/caddy/Caddyfile.production.example",
        "scripts/backup_db.sh",
        "scripts/restore_db.sh",
        "scripts/verify_deployment_static.py",
    }
    check("all_deployment_files_exist", all((ROOT / item).is_file() for item in files))
    if failures:
        print(json.dumps({"status": "failed", "checks": checks, "failures": failures}, indent=2))
        return 1

    contents = {item: read(item) for item in files}
    compose = contents["compose.yaml"]
    env_example = contents[".env.example"]
    dockerfiles = "\n".join(
        contents[item] for item in files if item.endswith("Dockerfile")
    )
    all_deployment_text = "\n".join(contents.values())

    services_section = compose.split("\nservices:\n", 1)[1].split("\nnetworks:\n", 1)[0]
    service_blocks = {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
            services_section,
            re.MULTILINE | re.DOTALL,
        )
    }

    services = {
        "reverse-proxy",
        "frontend",
        "migrate",
        "backend",
        "worker",
        "lreca",
        "postgres",
        "redis",
    }
    check(
        "required_services_declared",
        all(re.search(rf"^  {re.escape(service)}:$", compose, re.MULTILINE) for service in services),
    )
    check("service_blocks_parse_exactly", set(service_blocks) == services)
    check("only_one_host_ports_mapping", compose.count("\n    ports:\n") == 1)
    proxy_start = compose.index("  reverse-proxy:")
    frontend_start = compose.index("  frontend:")
    check("only_reverse_proxy_publishes_port", "\n    ports:\n" in compose[proxy_start:frontend_start])
    check(
        "parsed_only_reverse_proxy_publishes_port",
        {
            name
            for name, block in service_blocks.items()
            if re.search(r"^    ports:$", block, re.MULTILINE)
        }
        == {"reverse-proxy"},
    )
    check("no_latest_image_tags", not re.search(r"image:\s*[^\s]+:latest(?:\s|$)", compose))
    check("postgres_pinned", "image: postgres:16.10-bookworm" in compose)
    check("redis_pinned", "image: redis:7.4.5-alpine" in compose)
    check("caddy_pinned", "image: caddy:2.10.2-alpine" in compose)
    check(
        "local_application_images_versioned",
        all(
            f"image: llps-explorer-{name}:0.10.0" in compose
            for name in ("backend", "frontend", "worker", "lreca")
        ),
    )
    check("redis_aof_enabled", "--appendonly\n      - \"yes\"" in compose)
    check("postgres_named_volume", "postgres-data:/var/lib/postgresql/data" in compose)
    check("redis_named_volume", "redis-data:/data" in compose)
    check("migration_is_one_shot", 'restart: "no"' in compose and '"upgrade", "head"' in compose)
    check("backend_defaults_to_one_scheduler_process", "${BACKEND_WEB_WORKERS:-1}" in compose)
    check("checkpoint_mount_is_read_only", "target: /models/lreca\n        read_only: true" in compose)
    check("lreca_has_one_model_process", 'LRECA_MODEL_PROCESSES: "1"' in compose)
    check(
        "lreca_uses_separate_service_and_science_environments",
        "/opt/service-venv" in contents["docker/lreca/Dockerfile"]
        and "/opt/lreca-venv" in contents["docker/lreca/Dockerfile"]
        and "LRECA_PYTHON=/opt/lreca-venv/bin/python" in contents["docker/lreca/Dockerfile"],
    )
    check(
        "lreca_runtime_retains_git_identity",
        "git -C /opt/lreca rev-parse HEAD" in contents["docker/lreca/Dockerfile"]
        and "rm -rf /opt/lreca/.git" not in contents["docker/lreca/Dockerfile"],
    )
    lreca_dockerfile = contents["docker/lreca/Dockerfile"]
    check(
        "lreca_source_fetch_excludes_unneeded_blobs",
        "fetch --depth 1 --filter=blob:none" in lreca_dockerfile
        and "sparse-checkout init --no-cone" in lreca_dockerfile,
    )
    check(
        "lreca_sparse_source_is_explicitly_allowlisted",
        all(
            source_path in lreca_dockerfile
            for source_path in (
                "/Demo/code_for_model_testing/RCNN_ECA_personal_test.py",
                "/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py",
                (
                    "/Demo/code_for_model_testing/RCNN_ECA_saliency/"
                    "saliency_function/verify/RCNN_ECA_saliency_verify_gradCAM_fortest.py"
                ),
                (
                    "/Demo/code_for_model_testing/RCNN_ECA_saliency/"
                    "LCRs_process/split_LCRs_segment_forsingle.py"
                ),
                "/Data/pos_dataset/pos_word_list_human.txt",
                "/Data/neg_dataset/neg_word_list_human.txt",
            )
        ),
    )
    check(
        "lreca_source_and_git_objects_reject_model_weights",
        "remote remove origin" in lreca_dockerfile
        and "find /opt/lreca -type f" in lreca_dockerfile
        and "git -C /opt/lreca ls-tree -r --name-only HEAD" in lreca_dockerfile
        and "git -C /opt/lreca cat-file -e" in lreca_dockerfile,
    )
    check("internal_network_declared", "app-internal:\n    driver: bridge\n    internal: true" in compose)
    check("long_running_services_restart", compose.count("restart: unless-stopped") >= 7)
    check("healthchecks_declared", compose.count("healthcheck:") == 7)
    check(
        "every_long_running_service_has_healthcheck",
        all("\n    healthcheck:\n" in f"\n{service_blocks[name]}" for name in services - {"migrate"}),
    )
    check("application_images_read_only", compose.count("read_only: true") >= 7)
    application_services = {"reverse-proxy", "frontend", "migrate", "backend", "worker", "lreca"}
    check(
        "application_services_are_explicitly_read_only",
        all(
            re.search(r"^    read_only: true$", service_blocks[name], re.MULTILINE)
            or "*app-security" in service_blocks[name]
            for name in application_services
        ),
    )
    check(
        "application_services_are_explicitly_nonroot",
        all(
            (
                (
                    match := re.search(
                        r'^    user: "([^\"]+)"$', service_blocks[name], re.MULTILINE
                    )
                )
                and not match.group(1).startswith("0:")
            )
            or "*app-security" in service_blocks[name]
            for name in application_services
        ),
    )
    check(
        "no_privileged_or_host_namespace_modes",
        not re.search(r"(?m)^\s+(?:privileged:\s*true|network_mode:\s*host|pid:\s*host)", compose),
    )
    check("no_docker_socket_mount", "/var/run/docker.sock" not in compose)
    check(
        "critical_dependency_conditions_declared",
        "condition: service_completed_successfully" in service_blocks["backend"]
        and service_blocks["worker"].count("condition: service_healthy") >= 3
        and service_blocks["reverse-proxy"].count("condition: service_healthy") == 2,
    )
    check(
        "no_windows_absolute_paths",
        not re.search(r"(?i)(?:^|[\s\"'=])[a-z]:[\\/]", all_deployment_text),
    )

    required_env = {
        "APP_ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "SESSION_SECRET",
        "ANALYSIS_RETENTION_DAYS",
        "LRECA_SERVICE_URL",
        "LRECA_CHECKPOINT_PATH",
        "LRECA_DEVICE",
        "LRECA_KDE_PROMINENCE",
        "SEG_EXECUTABLE_PATH",
        "ENSEMBLE_THRESHOLD",
        "PUBLIC_BASE_URL",
        "CORS_ALLOWED_ORIGINS",
        "LOG_LEVEL",
        "RATE_LIMIT_ANALYSIS_REQUESTS",
    }
    declared_env = {
        line.split("=", 1)[0]
        for line in env_example.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    check("required_environment_documented", required_env <= declared_env)
    check("secret_placeholders_are_nonliteral", env_example.count("replace-with-") >= 5)
    check("env_example_has_no_private_key", "PRIVATE KEY-----" not in env_example)

    checkpoint_extensions = r"(?:pt|pth|ckpt|safetensors|onnx|h5|hdf5)"
    check(
        "checkpoint_never_copied",
        not re.search(rf"(?im)^\s*(?:COPY|ADD)\b[^\n]*\.{checkpoint_extensions}\b", dockerfiles),
    )
    check("frontend_is_multistage", contents["docker/frontend/Dockerfile"].count("FROM ") >= 3)
    check("frontend_node_is_pinned", "node:24.19.0-bookworm-slim" in contents["docker/frontend/Dockerfile"])
    check("frontend_uses_production_server", 'CMD ["node", "server.js"]' in dockerfiles)
    check("frontend_does_not_use_next_dev", "next dev" not in contents["docker/frontend/Dockerfile"])
    check("backend_python_is_pinned", "python:3.12.13-slim-bookworm" in contents["docker/backend/Dockerfile"])
    check("worker_python_is_pinned", "python:3.12.13-slim-bookworm" in contents["docker/worker/Dockerfile"])
    check("lreca_python_is_pinned", "python:3.10.19-slim-bookworm" in contents["docker/lreca/Dockerfile"])
    check("lreca_commit_is_pinned", "0b4b48ab7870529a34028c6e30dfba42eddbf215" in contents["docker/lreca/Dockerfile"])
    check("seg_uses_pinned_installer", "scripts/setup_seg.py --platform linux-x64" in contents["docker/worker/Dockerfile"])
    check("x64_scientific_services_are_explicit", compose.count("platform: linux/amd64") == 2)
    check("seg_build_runs_version", "segmasker -version" in contents["docker/worker/Dockerfile"])
    check("seg_build_runs_sequence_probe", "QQQQQQQQQQQQ" in contents["docker/worker/Dockerfile"])
    worker_health = contents["docker/worker/healthcheck.py"]
    check(
        "worker_health_uses_rq_registration_api",
        "Worker.all(connection=connection)" in worker_health,
    )
    check(
        "worker_health_binds_container_and_queue",
        "worker.hostname != hostname" in worker_health
        and "queue_name not in worker.queue_names()" in worker_health,
    )
    check(
        "worker_health_rejects_stale_or_suspended_registration",
        "worker.last_heartbeat" in worker_health
        and "worker.worker_ttl + 60" in worker_health
        and 'RUNNABLE_STATES = frozenset({"started", "idle", "busy"})' in worker_health,
    )
    check(
        "worker_health_is_installed_and_invoked",
        "docker/worker/healthcheck.py /opt/llps/worker_healthcheck.py"
        in contents["docker/worker/Dockerfile"]
        and '["CMD", "python", "/opt/llps/worker_healthcheck.py"]' in compose,
    )
    check("runtime_users_are_nonroot", dockerfiles.count("USER ") >= 4 and "USER root" not in dockerfiles)

    caddy = contents["docker/caddy/Caddyfile"]
    check("caddy_routes_api_to_backend", "@api path /api/*" in caddy and "reverse_proxy backend:8000" in caddy)
    check("caddy_routes_ui_to_frontend", "reverse_proxy frontend:3000" in caddy)
    check("caddy_limits_request_body", "max_size 6MB" in caddy)
    check("api_cache_is_private_no_store", 'Cache-Control "private, no-store' in caddy)
    for header in (
        "X-Content-Type-Options",
        "Referrer-Policy",
        "X-Frame-Options",
        "Content-Security-Policy",
    ):
        check(f"caddy_header_{header.lower()}", header in caddy)
    check("local_caddy_disables_https", "auto_https off" in caddy)
    check(
        "future_domain_config_is_inactive",
        "Caddyfile.production.example" not in compose
        and "{$PUBLIC_DOMAIN}" in contents["docker/caddy/Caddyfile.production.example"],
    )

    ignored = contents[".dockerignore"]
    for item in (
        ".git",
        ".env",
        "**/*.pt",
        "models",
        "**/node_modules",
        "frontend/.next",
        "**/*.db",
        "backups",
        "exports",
        "secrets",
        "certs",
        "**/*.key",
        "**/*.pem",
        "**/acme.json",
        "**/*.dump",
        "**/*.sql.gz",
    ):
        check(f"dockerignore_{item}", item in ignored)
    gitignored = contents[".gitignore"]
    for item in (".env", "*.pt", "backups/", "exports/", "postgres-data/", "redis-data/", "*.key", "*.pem"):
        check(f"gitignore_{item}", item in gitignored)
    check("backup_uses_pg_dump_custom", "pg_dump" in contents["scripts/backup_db.sh"] and "--format=custom" in contents["scripts/backup_db.sh"])
    check("backup_refuses_overwrite", 'if [ -e "$backup_file" ]' in contents["scripts/backup_db.sh"])
    check("restore_requires_explicit_flag", "--confirm-replace" in contents["scripts/restore_db.sh"])
    check("restore_is_transactional", "--single-transaction" in contents["scripts/restore_db.sh"])

    result = {
        "status": "passed" if not failures else "failed",
        "check_count": len(checks),
        "checks": checks,
        "failures": failures,
        "docker_runtime_required": False,
        "docker_build_or_runtime_claim": "not_performed_by_this_static_check",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
