"""Which user is the current request acting for? Set by the API layer and read by
tools, policy, agent and audit."""
import re
from contextlib import contextmanager
from contextvars import ContextVar

SAFE_NAME = re.compile(r"^[a-z0-9_]{3,32}$")
_current: ContextVar[str | None] = ContextVar("current_user", default=None)


def current() -> str | None:
    return _current.get()


@contextmanager
def as_user(user: str | None):
    token = _current.set(user)
    try:
        yield
    finally:
        _current.reset(token)