"""Environment handed to FreeCAD (pure Python).

FreeCAD, and Gmsh/CalculiX below it, need the usual process environment
(PATH, HOME, display, locale, snap/AppImage variables), but never the
user's credentials. Variables that look like secrets are dropped, so they
are not visible to FreeCAD, its solvers or code run by the opt-in 'python'
op.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Mapping, Optional

# Names such as GITHUB_TOKEN, AWS_SECRET_ACCESS_KEY, OPENAI_API_KEY, DB_PASSWORD, NPM_AUTH_TOKEN.
_SECRET_NAME = re.compile(
    r"(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|CREDENTIALS?|COOKIE|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY)S?(_|$)"
    r"|SECRET",
    re.IGNORECASE,
)
# Agent sockets give access to keys without reading them.
_SECRET_EXACT = {"SSH_AUTH_SOCK", "GPG_AGENT_INFO", "GOOGLE_APPLICATION_CREDENTIALS", "KUBECONFIG"}
# Values carrying credentials, e.g. DATABASE_URL=postgres://user:pass@host or a proxy with a password.
_CREDENTIAL_URL = re.compile(r"://[^/\s:@]+:[^/\s@]+@")


def is_secret(name: str, value: str) -> bool:
    if name.startswith("FCSKILL_"):
        return False
    return name.upper() in _SECRET_EXACT or bool(_SECRET_NAME.search(name)) or bool(_CREDENTIAL_URL.search(value))


def child_env(base: Optional[Mapping[str, str]] = None, **extra: str) -> Dict[str, str]:
    """A copy of ``base`` (default: os.environ) without secret-looking variables, plus ``extra``."""
    env = {k: v for k, v in (os.environ if base is None else base).items() if not is_secret(k, v)}
    env.update(extra)
    return env


def scrub_process_env() -> None:
    """Drop secret-looking variables from this process (FreeCAD run in-process)."""
    for k in [k for k, v in os.environ.items() if is_secret(k, v)]:
        del os.environ[k]
