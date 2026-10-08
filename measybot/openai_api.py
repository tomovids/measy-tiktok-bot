"""A small OpenAI client: one JSON chat call and one image call, with retries."""
from __future__ import annotations

import base64
import json
import time

import requests

API = "https://api.openai.com/v1"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class OpenAIError(Exception):
    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body

    @property
    def is_model_problem(self) -> bool:
        b = self.body.lower()
        return self.status in (400, 403, 404) and ("model" in b or "not found" in b)


class OpenAI:
    def __init__(self, api_key: str, timeout: float = 180, retries: int = 3,
                 session: requests.Session | None = None, sleep=time.sleep):
        self.key = api_key
        self.timeout = timeout
        self.retries = retries
        self.http = session or requests.Session()
        self.sleep = sleep

    def _post(self, path: str, body: dict) -> dict:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.http.post(f"{API}{path}", json=body, timeout=self.timeout,
                                   headers={"Authorization": f"Bearer {self.key}"})
            except requests.RequestException as e:
                last = OpenAIError(f"Network error calling OpenAI: {e}")
            else:
                if r.status_code == 200:
                    return r.json()
                last = OpenAIError(f"OpenAI {path} failed ({r.status_code}): {r.text[:500]}",
                                   r.status_code, r.text)
                if r.status_code not in RETRY_STATUS:
                    raise last
            if attempt < self.retries - 1:
                self.sleep([3, 10, 30][min(attempt, 2)])
        raise last  # type: ignore[misc]

    def chat_json(self, model: str, system: str, user: str) -> dict:
        data = self._post("/chat/completions", {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        })
        text = data["choices"][0]["message"]["content"] or ""
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise OpenAIError(f"The writer did not return JSON: {text[:300]}") from e

    def image(self, models: list[str], prompt: str, size: str, quality: str) -> tuple[bytes, str]:
        """Returns (image bytes, model used). Tries each model until one is available."""
        errors = []
        for model in models:
            try:
                data = self._post("/images/generations", {
                    "model": model, "prompt": prompt, "size": size, "quality": quality, "n": 1})
            except OpenAIError as e:
                if e.is_model_problem:
                    errors.append(f"{model}: {e}")
                    continue
                raise
            item = data["data"][0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"]), model
            if item.get("url"):
                r = self.http.get(item["url"], timeout=self.timeout)
                r.raise_for_status()
                return r.content, model
            raise OpenAIError(f"No image in the response from {model}.")
        raise OpenAIError("None of the image models worked:\n" + "\n".join(errors))
