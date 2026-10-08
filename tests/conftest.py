import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from measybot import config  # noqa: E402


@pytest.fixture
def cfg():
    return config.load_config()


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=None, headers=None):
        self.status_code = status_code
        self._data = data
        self.text = text if text is not None else json.dumps(data)
        self.headers = headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def close(self):
        pass


class FakeSession:
    """Answers queued responses in order and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.responses.pop(0)

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.responses.pop(0)


@pytest.fixture
def fake_session():
    return FakeSession
