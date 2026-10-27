"""Keep bundled library paths out of external CLI and system processes."""
import os
import sys


def external_env():
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        for key in ("LD_LIBRARY_PATH", "LIBPATH"):
            original = env.get(key + "_ORIG")
            if original is None:
                env.pop(key, None)
            else:
                env[key] = original
    return env
