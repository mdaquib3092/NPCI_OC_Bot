"""One interface to the language model, for Groq and local Ollama (both OpenAI-compatible).

The model is only asked for JSON; anything that goes wrong becomes an LLMError with a
kind the pipeline maps to a safe fallback (never a blank screen).
"""

import json
import re

from .config import Settings


class LLMError(Exception):
    def __init__(self, kind: str, message: str = ""):
        super().__init__(f"{kind}: {message}")
        self.kind = kind            # unavailable | rate_limit | timeout | invalid_json | disabled


def strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"<think>.*$", "", text, flags=re.DOTALL | re.IGNORECASE).strip()


def extract_json(text: str) -> dict:
    """Parse the first JSON object in the model output."""
    text = strip_think(text)
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        raise LLMError("invalid_json", "no JSON object in the reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError as e:
                    raise LLMError("invalid_json", str(e))
    repaired = _repair_truncated(text[start:])
    if repaired is not None:
        return repaired
    raise LLMError("invalid_json", "unterminated JSON object")


def _repair_truncated(text: str):
    """A reply cut off at the token limit: keep everything up to the last complete item and close the brackets."""
    for cut in [m.start() + 1 for m in re.finditer(r"[}\]]", text)][::-1]:
        head, stack, in_str, esc = text[:cut], [], False, False
        for ch in head:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_str:
            continue
        try:
            return json.loads(head.rstrip().rstrip(",") + "".join(reversed(stack)))
        except json.JSONDecodeError:
            continue
    return None


class LLMClient:
    """Wraps the OpenAI-compatible SDK. `complete_json(system, user)` returns a dict."""

    def __init__(self, settings: Settings = None, sdk_client=None):
        self.settings = settings or Settings.from_env()
        self._client = sdk_client

    @property
    def enabled(self) -> bool:
        s = self.settings
        if s.llm_provider == "none":
            return False
        if s.llm_provider == "groq" and not s.groq_api_key:
            return False
        return True

    def _sdk(self):
        if self._client is None:
            from openai import OpenAI

            s = self.settings
            if s.llm_provider == "groq":
                self._client = OpenAI(base_url=s.groq_base_url, api_key=s.groq_api_key, timeout=s.llm_timeout)
            else:
                self._client = OpenAI(base_url=s.ollama_base_url, api_key="ollama", timeout=s.llm_timeout)
        return self._client

    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        if not self.enabled:
            raise LLMError("disabled", "no language model configured")
        s = self.settings
        suffix = " /no_think" if s.llm_provider == "ollama" else ""
        extra = {"extra_body": {"reasoning_effort": "low"}} if s.llm_provider == "groq" else {}
        try:
            resp = self._sdk().chat.completions.create(
                model=s.model, temperature=0, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user + suffix}],
                response_format={"type": "json_object"}, **extra)
        except Exception as e:  # SDK errors differ by version; classify by message
            msg = str(e).lower()
            if "429" in msg or "rate" in msg and "limit" in msg:
                raise LLMError("rate_limit", str(e)[:200])
            if "timed out" in msg or "timeout" in msg:
                raise LLMError("timeout", str(e)[:200])
            raise LLMError("unavailable", str(e)[:200])
        return extract_json(resp.choices[0].message.content or "")
