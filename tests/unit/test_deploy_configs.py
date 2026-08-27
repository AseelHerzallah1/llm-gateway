"""Validate monitoring stack configuration files."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_prometheus_config_parses() -> None:
    path = ROOT / "deploy" / "prometheus" / "prometheus.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = data["scrape_configs"]
    assert any(job["job_name"] == "llm-gateway" for job in jobs)
    target = jobs[0]["static_configs"][0]["targets"][0]
    assert target == "app:8000"
    assert jobs[0]["metrics_path"] == "/metrics"


def test_grafana_datasource_provisioning_parses() -> None:
    path = ROOT / "deploy" / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    ds = data["datasources"][0]
    assert ds["type"] == "prometheus"
    assert ds["url"] == "http://prometheus:9090"
    assert ds["isDefault"] is True


def test_grafana_dashboard_provisioning_parses() -> None:
    path = ROOT / "deploy" / "grafana" / "provisioning" / "dashboards" / "dashboards.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    provider = data["providers"][0]
    assert provider["type"] == "file"
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"


def test_grafana_dashboard_json_parses() -> None:
    path = ROOT / "deploy" / "grafana" / "dashboards" / "llm-gateway.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["title"] == "LLM Gateway Overview"
    assert len(data["panels"]) >= 8
    assert data["uid"] == "llm-gateway-overview"


def test_docker_compose_config_is_valid() -> None:
    env_path = ROOT / ".env"
    env_example = ROOT / ".env.example"
    created_temp_env = False
    if not env_path.exists():
        assert env_example.exists(), ".env.example required for compose validation"
        shutil.copy(env_example, env_path)
        created_temp_env = True
    try:
        result = subprocess.run(
            ["docker", "compose", "config"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "llm-gateway-prometheus" in result.stdout
        assert "llm-gateway-grafana" in result.stdout
    finally:
        if created_temp_env and env_path.exists():
            env_path.unlink()
