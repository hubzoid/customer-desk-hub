"""Resolve the same declared/operator/stored values that SDK doctor checks."""
from __future__ import annotations

from pathlib import Path


def resolve(hub_dir: Path, name: str) -> str:
    from hubzoid import secretstore
    from hubzoid.assertions import hub_key
    from hubzoid.hubs import settings

    ref = settings.secret_ref(hub_dir, name) or f"env:{name}"
    parsed = secretstore.parse(ref)
    if parsed.provider != "env":
        return secretstore.resolve(parsed, hub_dir)
    # Prefer operator layers exactly as the SDK does. An env: reference also
    # has the SDK's hub/deployment store fallback when no operator value exists.
    env = settings._secret_env(hub_dir, None)
    if env.get(parsed.name):
        return secretstore.resolve(parsed, hub_dir, env=env)
    for candidate in (f"secret:hub/{hub_key(hub_dir)}/{parsed.name}", f"secret:deployment/{parsed.name}"):
        try:
            return secretstore.resolve(candidate, hub_dir, env=env)
        except secretstore.SecretError as exc:
            if exc.code != "secret_unavailable":
                raise
    raise KeyError(name)
