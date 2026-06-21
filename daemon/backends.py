#!/usr/bin/env python3
"""Pluggable inference backends.

kniox assumes NONE of these exist. The active backend is read from config.json (written
by setup AFTER detection), so swapping Ollama for vLLM/llama.cpp is a config change, not
a code change. Each backend implements: present(), models(), loaded(), generate().

  - OllamaBackend         native /api (fully wired)
  - OpenAICompatBackend   vLLM / llama.cpp server / LM Studio via /v1 (OpenAI-compatible)
  - NoneBackend           honest no-backend fallback: dispatch fails loudly, never silently
"""
from __future__ import annotations
import json, os, urllib.request


def _http_json(url, body=None, timeout=180):
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Backend:
    name = "base"

    def __init__(self, endpoint=None):
        self.endpoint = endpoint

    def present(self):          return False
    def models(self):           return []
    def loaded(self):           return []
    def generate(self, model, prompt):  raise NotImplementedError


class OllamaBackend(Backend):
    name = "ollama"

    def __init__(self, endpoint=None):
        self.endpoint = endpoint or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def present(self):
        try:
            _http_json(f"{self.endpoint}/api/version", timeout=3)
            return True
        except Exception:
            return False

    def models(self):
        try:
            data = _http_json(f"{self.endpoint}/api/tags", timeout=5)
            return [{"name": m.get("name"),
                     "size_gb": round(m.get("size", 0) / 1e9, 2) if m.get("size") else None}
                    for m in data.get("models", [])]
        except Exception:
            return []

    def loaded(self):
        try:
            data = _http_json(f"{self.endpoint}/api/ps", timeout=3)
            return [{"name": m.get("name"), "size_gb": round(m.get("size", 0) / 1e9, 2)}
                    for m in data.get("models", [])]
        except Exception:
            return []

    def generate(self, model, prompt):
        body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
        return _http_json(f"{self.endpoint}/api/generate", body, timeout=300).get("response", "")


class OpenAICompatBackend(Backend):
    """vLLM, llama.cpp server, LM Studio — all speak the OpenAI HTTP API."""

    def __init__(self, name, endpoint):
        self.name = name
        self.endpoint = endpoint

    def present(self):
        try:
            _http_json(f"{self.endpoint}/v1/models", timeout=3)
            return True
        except Exception:
            return False

    def models(self):
        try:
            data = _http_json(f"{self.endpoint}/v1/models", timeout=5)
            return [{"name": m.get("id"), "size_gb": None} for m in data.get("data", [])]
        except Exception:
            return []

    def loaded(self):
        return self.models()

    def generate(self, model, prompt):
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                           "stream": False}).encode()
        out = _http_json(f"{self.endpoint}/v1/chat/completions", body, timeout=300)
        return out["choices"][0]["message"]["content"]


class NoneBackend(Backend):
    name = "none"

    def present(self):
        return True   # the absence of a backend is itself a known, valid state

    def generate(self, model, prompt):
        raise RuntimeError("no inference backend configured; run `kx setup` to detect or install one")


_OPENAI_DEFAULTS = {"vllm": "http://localhost:8000",
                    "llamacpp": "http://localhost:8080",
                    "lmstudio": "http://localhost:1234",
                    "openai-compatible": "http://localhost:8000"}


def get_backend(config):
    """Resolve the configured backend. Unknown/absent -> NoneBackend (honest)."""
    name = (config or {}).get("backend")
    endpoint = (config or {}).get("endpoint")
    if name == "ollama":
        return OllamaBackend(endpoint)
    if name in _OPENAI_DEFAULTS:
        return OpenAICompatBackend(name, endpoint or _OPENAI_DEFAULTS[name])
    return NoneBackend()
