"""Container pre-flight, with `docker` replaced by canned output (no Docker needed)."""

import json
import subprocess
from typing import Any

import pytest

from gateway import stack
from gateway.stack import StackNotReady, check_stack, describe

PS = "gateway-postgres-1\tgateway\ngateway-redis-1\tgateway\ncase_app_dev\talt_phase11\np6_fwd\t\n"


def _compose(**health: str) -> str:
    return "\n".join(
        json.dumps({"Service": name, "State": "running", "Health": h}) for name, h in health.items()
    )


def fake_docker(monkeypatch: pytest.MonkeyPatch, ps: tuple[int, str], compose: tuple[int, str]) -> None:
    def run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        code, out = ps if args[1] == "ps" else compose
        return subprocess.CompletedProcess(args, code, out, "boom" if code else "")

    monkeypatch.setattr(stack.subprocess, "run", run)


def test_healthy_stack_reports_other_projects_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_docker(monkeypatch, (0, PS), (0, _compose(postgres="healthy", redis="healthy")))
    status = check_stack()
    assert status.services == {"postgres": "healthy", "redis": "healthy"}
    assert status.other_containers == ["case_app_dev", "p6_fwd"]
    assert "WARNING: 2 other project container(s)" in describe(status)


@pytest.mark.parametrize(
    ("ps", "compose", "message"),
    [
        ((1, ""), (0, ""), "`docker ps` failed"),
        ((0, PS), (1, ""), "`docker compose ps` failed"),
        ((0, PS), (0, _compose(redis="healthy")), "postgres is not running"),
        ((0, PS), (0, _compose(postgres="starting", redis="healthy")), "postgres is running/starting"),
    ],
)
def test_unhealthy_stack_raises(
    monkeypatch: pytest.MonkeyPatch, ps: tuple[int, str], compose: tuple[int, str], message: str
) -> None:
    fake_docker(monkeypatch, ps, compose)
    with pytest.raises(StackNotReady, match=message):
        check_stack()


def test_missing_docker_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*_: Any, **__: Any) -> None:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(stack.subprocess, "run", run)
    with pytest.raises(StackNotReady, match="WSL integration"):
        check_stack()
