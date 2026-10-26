"""Container pre-flight for smoke and eval runs: Docker answers and Gateway's own services are healthy.

Run before anything touches the database or an LLM, so a run never starts on a stack that is down
(a Docker restart stops Gateway's containers, while other projects' restart-always containers come
back on their own and eat the shared RAM).
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from gateway.errors import GatewayError

ROOT = Path(__file__).resolve().parent.parent
SERVICES = ("postgres", "redis")
COMPOSE_PROJECT = "gateway"


class StackNotReady(GatewayError):
    """Docker is unreachable or a Gateway compose service is not running and healthy."""


@dataclass
class StackStatus:
    services: dict[str, str] = field(default_factory=dict)
    other_containers: list[str] = field(default_factory=list)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, cwd=ROOT, timeout=30)
    except FileNotFoundError as exc:
        raise StackNotReady(
            "`docker` not found. Enable Docker Desktop WSL integration for this distro."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise StackNotReady(f"`{' '.join(args)}` timed out. Is Docker Desktop running?") from exc


def check_stack() -> StackStatus:
    r = _run(["docker", "ps", "--format", '{{.Names}}\t{{.Label "com.docker.compose.project"}}'])
    if r.returncode != 0:
        raise StackNotReady(f"`docker ps` failed: {r.stderr.strip() or r.stdout.strip()}")
    status = StackStatus(
        other_containers=sorted(
            name
            for name, _, project in (line.partition("\t") for line in r.stdout.splitlines() if line.strip())
            if project != COMPOSE_PROJECT
        )
    )
    r = _run(["docker", "compose", "ps", "--format", "json"])
    if r.returncode != 0:
        raise StackNotReady(f"`docker compose ps` failed: {r.stderr.strip()}")
    running = {s["Service"]: s for s in (json.loads(line) for line in r.stdout.splitlines() if line.strip())}
    for name in SERVICES:
        svc = running.get(name)
        if svc is None or svc.get("Health") != "healthy":
            state = "not running" if svc is None else f"{svc.get('State')}/{svc.get('Health') or 'no health'}"
            raise StackNotReady(f"compose service {name} is {state}; run `docker compose up -d --wait`")
        status.services[name] = "healthy"
    return status


def describe(status: StackStatus) -> str:
    line = "stack: " + ", ".join(f"{k} {v}" for k, v in status.services.items())
    if status.other_containers:
        line += (
            f"\nWARNING: {len(status.other_containers)} other project container(s) running "
            f"({', '.join(status.other_containers)}); CLAUDE.md asks for them to be stopped before eval runs "
            "(see docs/stopped_containers.txt)"
        )
    return line
