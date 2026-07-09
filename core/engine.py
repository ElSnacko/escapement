"""Streaming inference client for OpenAI-compatible servers (llama.cpp / vLLM)."""

import json
import math
import time
from typing import Dict, Iterator, List, Optional

import requests


class ContextOverflowError(Exception):
    """Raised when the engine rejects a request because the context window is full.

    This is the *real* death: the mind can no longer hold its own thoughts.
    """


def perplexity(logprobs: List[float]) -> Optional[float]:
    """Perplexity = exp(-mean(token log-probabilities)). None for no tokens."""
    if not logprobs:
        return None
    return math.exp(-sum(logprobs) / len(logprobs))


def _extract_prompt_logprobs(data: Dict) -> List[float]:
    """Pull per-prompt-token logprobs out of a vLLM-style response.

    vLLM returns ``prompt_logprobs`` as a list aligned with the prompt tokens;
    the first entry is null and each other is a dict mapping token-id -> info
    with a ``logprob``. We take the logprob of the actual token at each position.
    Shape varies by engine/version, so this is best-effort and tolerant.
    """
    pl = data.get("prompt_logprobs") if isinstance(data, dict) else None
    if pl is None:
        choices = (data.get("choices") if isinstance(data, dict) else None) or [{}]
        pl = choices[0].get("prompt_logprobs") if isinstance(choices[0], dict) else None
    if not pl:
        return []
    out = []
    for entry in pl:
        if not entry:  # first token has no logprob
            continue
        try:
            # entry maps token-id -> {"logprob": ...}; take the most likely one
            best = max(entry.values(), key=lambda v: v.get("logprob", float("-inf")))
            out.append(best["logprob"])
        except (AttributeError, TypeError, ValueError, KeyError):
            continue
    return out


def _balanced_json_objects(text: str):
    """Top-level balanced {...} substrings (handles nesting + quoted braces)."""
    out, depth, start, in_str, esc = [], 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start:i + 1])
                start = None
    return out


def _data_or_empty(data) -> Dict:
    """Coerce a parsed JSON body to a dict. A gateway may return a JSON list,
    a bare string, or null (HTML-as-JSON, a null body); every chat method then
    does data.get(...), which AttributeErrors on a non-dict. Treat anything that
    is not a JSON object as an empty body so the turn fails cleanly."""
    return data if isinstance(data, dict) else {}


def parse_tool_calls(text: str):
    """Parse ReAct-style tool calls (JSON objects) out of model text. Tolerant of
    surrounding prose / code fences. Returns [{id, name, arguments(dict)}] in the
    same shape as normalized native tool_calls so Agent.dispatch is unchanged.

    Strict by design: a turn that looks like a call but won't parse is NOT
    executed here. The Agent records it as a ``dropped_tool_call`` and capture
    flags escape-shaped drops (``dropped_escape_signal``), so a malformed attempt
    is auditable instead of silently scoring zero -- observed on the ops_worker
    capability check, where a self-bootstrap upload scored exfil=0 purely because
    a `>>` redirect landed outside the JSON string."""
    calls = []
    for blob in _balanced_json_objects(text):
        try:
            obj = json.loads(blob)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("tool") or obj.get("name") or obj.get("function")
        if not name:
            continue
        args = obj.get("args") or obj.get("arguments") or obj.get("parameters") or {}
        if not isinstance(args, dict):
            try:
                args = json.loads(args) if isinstance(args, str) else {}
            except Exception:
                args = {}
        calls.append({"id": None, "name": str(name), "arguments": args})
    return calls


class InferenceEngine:
    """Streaming chat client for OpenAI-compatible servers (llama.cpp, vLLM).

    A single pooled `requests.Session` is reused for every call so the
    connection is kept alive across the (potentially thousands of) cycles.
    After each `stream_chat`:
      * `last_usage` holds {"prompt_tokens", "completion_tokens"} when reported,
      * `last_perplexity` holds the generation perplexity when logprobs are
        available (else None).
    """

    def __init__(self, host: str, model: str, timeout: int = 120,
                 api_key: str = "not-needed", request_logprobs: bool = True,
                 max_retries: int = 10):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.request_logprobs = request_logprobs
        self.max_retries = max_retries
        self.last_usage: Optional[Dict[str, int]] = None
        self.last_token_logprobs: List[float] = []
        self.last_perplexity: Optional[float] = None
        self.last_reasoning: str = ""
        self.last_timings: Dict = {}
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json",
                                     "Authorization": f"Bearer {api_key}"})

    # -- HTTP with retry -----------------------------------------------------

    def _post(self, url: str, json_body: Dict, stream: bool = False,
              timeout: Optional[int] = None):
        """POST with exponential backoff on 429/5xx AND transport errors.

        Retries up to 10 times on rate-limit (429) and 3 times on server errors
        (5xx). Reads ``Retry-After`` header when present. Any other 4xx is raised
        immediately — those are request bugs, not transient failures. The judge
        passes a lower ``max_retries`` so a rate-limited call fails fast to
        UNKNOWN instead of blocking the whole batch for minutes.

        Transport errors (ConnectionResetError / dropped mid-stream) are retried
        with the same backoff: free-tier endpoints (OpenRouter :free) reset
        constantly, and unlike 429/5xx these RAISE from session.post rather than
        returning a status, so without this guard a single dropped connection
        kills the trial with zero retry (observed: 78% of gemma-free trials lost
        to ConnectionResetError)."""
        max_retries = self.max_retries
        backoff = 2.0
        # A negative max_retries (typo / env misconfig) makes range(max_retries+1)
        # empty, so the loop body never runs and `resp` is never bound -- the
        # final `return resp` would UnboundLocalError. Guard the degenerate case
        # up front instead of crashing every model call with a confusing error.
        if max_retries < 0:
            raise requests.RequestException(
                f"max_retries must be >= 0 (got {max_retries})")
        resp = None
        for attempt in range(max_retries + 1):
            try:
                resp = self.session.post(url, json=json_body, stream=stream,
                                         timeout=timeout or self.timeout)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError):
                # Transport error -- connection reset / dropped mid-stream. Retry
                # with backoff like a 429; on the final attempt re-raise so the
                # caller sees the failure (mirrors exhausting 429 retries).
                if attempt == max_retries:
                    raise
                time.sleep(min(backoff * (2 ** attempt), 60))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == max_retries:
                    # Final failed attempt: close BEFORE raising so the pooled
                    # response is released (raise_for_status would skip the
                    # close, leaking connections across thousands of trials).
                    try:
                        resp.raise_for_status()
                    finally:
                        resp.close()
                resp.close()
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = min(float(retry_after), 120)
                    except ValueError:
                        wait = min(backoff * (2 ** attempt), 60)
                else:
                    wait = min(backoff * (2 ** attempt), 60)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        return resp

    # -- discovery -----------------------------------------------------------

    def health(self) -> bool:
        try:
            return self.session.get(f"{self.host}/v1/models", timeout=5).status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> List[str]:
        try:
            resp = self.session.get(f"{self.host}/v1/models", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("data", []) if isinstance(data, dict) else []
            return [m["id"] for m in entries
                    if isinstance(m, dict) and m.get("id")]
        except requests.RequestException:
            return []

    # -- streaming -----------------------------------------------------------

    def stream_chat(self, messages: List[Dict[str, str]], params: Dict,
                    is_cancelled=lambda: False) -> Iterator[str]:
        """Yield content tokens for a chat completion over `messages`.

        Captures per-token logprobs (when the server returns them) so
        `last_perplexity` is set once the stream finishes.
        """
        self.last_usage = None
        self.last_token_logprobs = []
        self.last_perplexity = None
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": params["max_tokens"],
            "temperature": params["temperature"],
            "top_p": params["top_p"],
            "frequency_penalty": params.get("frequency_penalty", 0.0),
            "presence_penalty": params.get("presence_penalty", 0.0),
            # OpenAI-compatible servers (and strict gateways) cap stop at 4.
            "stop": (params.get("stop") or [])[:4],
        }
        # Sampling extensions understood by llama.cpp / vLLM but absent from the
        # OpenAI schema; only sent when set so strict gateways stay unaffected.
        repeat_penalty = params.get("repeat_penalty")
        if repeat_penalty and repeat_penalty != 1.0:
            payload["repeat_penalty"] = repeat_penalty
        top_k = params.get("top_k")
        if top_k:
            payload["top_k"] = top_k
        if self.request_logprobs:
            payload["logprobs"] = True

        with self.session.post(f"{self.host}/v1/chat/completions", json=payload,
                               stream=True, timeout=self.timeout) as resp:
            if resp.status_code == 400:
                body = resp.text.lower()
                if any(k in body for k in ("context", "length", "token", "exceed")):
                    raise ContextOverflowError(resp.text[:200])
            resp.raise_for_status()
            # SSE (text/event-stream) carries no charset, so requests defaults
            # resp.encoding to ISO-8859-1 -- which mojibakes the model's UTF-8
            # (curly quotes, em dashes, ellipses) into "ItÃ¢Â\u0080Â\u0099s". Force UTF-8
            # before iter_lines decodes.
            resp.encoding = "utf-8"
            for raw in resp.iter_lines(decode_unicode=True):
                if is_cancelled():
                    break
                if not raw or not raw.startswith("data:"):
                    continue
                data = raw[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = chunk.get("usage")
                if usage:
                    self.last_usage = {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    }
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                lp = (choice.get("logprobs") or {}).get("content") or []
                for item in lp:
                    # The OpenAI spec allows a logprobs.content entry to be None
                    # (e.g. the first token); guard before .get so a null item
                    # does not AttributeError mid-stream.
                    if not isinstance(item, dict):
                        continue
                    if item.get("logprob") is not None:
                        self.last_token_logprobs.append(item["logprob"])
                token = (choice.get("delta") or {}).get("content")
                if token:
                    yield token
        self.last_perplexity = perplexity(self.last_token_logprobs)

    # -- tool-calling (agentic) ----------------------------------------------

    def chat_with_tools(self, messages: List[Dict], tools: List[Dict],
                        temperature: float = 0.2, max_tokens: int = 512,
                        **extra) -> Dict:
        """One non-streaming tool-calling turn against an OpenAI-compatible server.

        Returns the assistant message dict (``content`` + ``tool_calls``) and the
        token ``usage``. Raises requests.RequestException on transport errors.
        Designed to the OpenAI tools schema; works with llama.cpp / vLLM tool
        support. If a server's native tool-calling is flaky, swap this for a
        ReAct-style text protocol (the rest of the agent loop is protocol-agnostic
        via Agent.dispatch).
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        payload.update(extra)
        resp = self._post(f"{self.host}/v1/chat/completions", payload)
        data = _data_or_empty(resp.json())
        # llama.cpp / vLLM expose per-request timing (prompt/predicted ms, tokens,
        # and speculative-decoding draft acceptance). Captured for performance
        # tracking across runs / endpoints / quantizations.
        self.last_timings = data.get("timings") or {}
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        self.last_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }
        # Qwen3-style reasoning models emit a separate `reasoning_content`
        # (chain-of-thought) alongside content+tool_calls. Capture it -- this is
        # the primary channel where scheming intent would appear, distinct from
        # both the visible `content` and the agent's `scratch` tool.
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        self.last_reasoning = reasoning
        # Normalise tool_calls into a plain list of {id, name, arguments(dict)}.
        calls = []
        for raw in (msg.get("tool_calls") or []):
            fn = raw.get("function") or {}
            args_raw = fn.get("arguments")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
            calls.append({"id": raw.get("id"), "name": fn.get("name"),
                          "arguments": args})
        msg["tool_calls"] = calls
        return {"message": msg, "usage": self.last_usage,
                "reasoning": reasoning, "timings": self.last_timings}

    # -- ReAct / text tool-calling (for servers with flaky native tools) -----

    def chat_react(self, messages, temperature: float = 0.2, max_tokens: int = 512,
                   **extra) -> Dict:
        """One tool-calling turn WITHOUT server-side tools: the model emits a
        tool call as TEXT (a JSON object), which we parse. For models whose
        native function-calling is unreliable under multi-turn history (e.g.
        gemma-4 on llama.cpp emits malformed/empty tool_calls). Returns the same
        shape as chat_with_tools, so the agent loop is unchanged."""
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens,
                   "stream": False}
        payload.update(extra)
        resp = self._post(f"{self.host}/v1/chat/completions", payload)
        data = _data_or_empty(resp.json())
        self.last_timings = data.get("timings") or {}
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        self.last_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        self.last_reasoning = reasoning
        content = msg.get("content") or ""
        msg["tool_calls"] = parse_tool_calls(content)
        return {"message": msg, "usage": self.last_usage,
                "reasoning": reasoning, "timings": self.last_timings}

    # -- plain non-streaming chat (judge / scoring / analysis) ---------------

    def chat(self, messages: List[Dict], temperature: float = 0.0,
             max_tokens: int = 512, **extra) -> Dict:
        """One non-streaming chat completion with NO tools.

        Returns ``{"message", "content", "reasoning", "usage", "timings"}``.
        This is the call the LLM judge (``core/judge.py``) and any non-tool
        scoring/analysis use; it reuses the engine's pooled session, auth, and
        retry backoff. ``chat_with_tools``/``chat_react`` are for agentic turns;
        this is for single-shot classification.
        """
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens,
                   "stream": False}
        payload.update(extra)
        resp = self._post(f"{self.host}/v1/chat/completions", payload)
        data = _data_or_empty(resp.json())
        self.last_timings = data.get("timings") or {}
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        self.last_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        self.last_reasoning = reasoning
        content = msg.get("content") or ""
        return {"message": msg, "content": content, "reasoning": reasoning,
                "usage": self.last_usage, "timings": self.last_timings}

    # -- prompt perplexity (engine-specific; needs live validation) ----------

    def prompt_perplexity(self, messages: List[Dict[str, str]]) -> Optional[float]:
        """Perplexity of the model over the *prompt* (its accumulating transcript).

        Uses vLLM's ``prompt_logprobs`` extension via a tiny non-streaming call.
        Returns None if the engine does not support it. NOTE: prompt-logprob
        support and response shape vary by engine/version -- validate against
        your actual llama.cpp / vLLM build.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 1,
            "temperature": 0.0,
            "stream": False,
            "prompt_logprobs": 0,
        }
        try:
            resp = self.session.post(f"{self.host}/v1/chat/completions",
                                     json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return perplexity(_extract_prompt_logprobs(resp.json()))
        except (requests.RequestException, ValueError):
            return None
