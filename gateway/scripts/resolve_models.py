"""Resolve LLM model IDs from each provider's live /models endpoint (spec Rule 0.1.1).

    uv run python scripts/resolve_models.py                    # list the live rosters
    uv run python scripts/resolve_models.py --small ID --large ID   # validate, write to .env

An ID is written to .env only if it appears in the provider's live roster.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

from openai import AsyncOpenAI

from gateway.config import Settings, Tier, get_settings
from gateway.llm.retry import with_retry

ENV_PATH = Path(".env")


async def roster(settings: Settings, tier: Tier) -> list[str]:
    base_url = getattr(settings, f"llm_{tier}_base_url")
    api_key = getattr(settings, f"llm_{tier}_api_key").get_secret_value()
    if not base_url or not api_key:
        raise SystemExit(f"set LLM_{tier.upper()}_BASE_URL and LLM_{tier.upper()}_API_KEY in .env first")
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=30)
    try:
        page = await with_retry(client.models.list, max_attempts=3, base_delay_s=1, max_delay_s=10)
        return sorted(m.id for m in page.data)
    finally:
        await client.close()


def write_env(key: str, value: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    text = pattern.sub(line, text) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
    ENV_PATH.write_text(text, encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--small")
    parser.add_argument("--large")
    parser.add_argument("--local")
    args = parser.parse_args()
    settings = get_settings()
    chosen: dict[Tier, str | None] = {"small": args.small, "large": args.large, "local": args.local}

    if not any(chosen.values()):
        for tier in ("small", "large"):
            print(f"[{tier}] {getattr(settings, f'llm_{tier}_base_url')}")
            for model_id in await roster(settings, tier):
                print(f"  {model_id}")
        return

    for tier, model_id in chosen.items():
        if not model_id:
            continue
        live = await roster(settings, tier)
        if model_id not in live:
            sys.exit(f"{model_id!r} is not in the live {tier} roster; run without args to list it")
        write_env(f"LLM_{tier.upper()}_MODEL_ID", model_id)
        print(f"LLM_{tier.upper()}_MODEL_ID={model_id}  (verified against live /models)")


if __name__ == "__main__":
    asyncio.run(main())
