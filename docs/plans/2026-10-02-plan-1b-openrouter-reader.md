# Plan 1b: Live Image Reader through OpenRouter

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `openrouter` image reader, so `extract` reads the order image with a live vision model
instead of replaying `tests/fixtures/sample_order.json`.

**Architecture:**
- `OpenRouterReader` implements the existing `ImageReader` protocol (`readers/base.py`).
- It sends one chat-completions request to OpenRouter, which reaches many vendors with one key:
  temperature 0, JSON mode, the `Order` JSON Schema in the system prompt, and the prepared image as a
  data URL. It validates the reply against `Order`.
- The request asks OpenRouter to route only to providers that don't store or train on prompts
  (`provider.data_collection: deny`), because orders carry customers' personal data.
- Every failure becomes a `ReaderError`, which the CLI already reports with exit code 1. That covers:
  - a missing or mangled key;
  - HTTP errors and upstream errors (including errors inside an HTTP 200);
  - timeouts;
  - cut-off or empty replies;
  - invalid orders.
- Error messages never contain:
  - the API key: every message passes through one redacting cleaner, and the cleaner runs before any
    truncation;
  - the model's reply, including the names of unexpected fields;
  - control characters: upstream text is reduced to one printable line of at most 200 characters.
- The rest of the pipeline is unchanged: OCR cross-check, invariants, review, approve.

**Tech Stack:** as Plan 1, plus `httpx` (HTTP client; its `MockTransport` fakes OpenRouter in tests).

**Conventions:** as Plan 1.
- Repo root: `/Users/mougalal/Desktop/fakturama-image-to-cash`. Git identity is repo-local, there is no
  remote, and commits use conventional messages **with no attribution trailer**.
- The key is read only from `OPENROUTER_API_KEY`. Locally it lives in the git-ignored `.env`, and live
  runs use `uv run --env-file .env ...`. Never write the key into code, tests, docs or commands.

## Spike findings (2026-10-02, sample image, free models)

These decide the design:

- **Schema-constrained decoding is unusable with Pydantic's schema.** With
  `response_format: json_schema`, a provider rejected the schema: "lookaround assertions are not
  supported by the configured guided-decoding backend". Pydantic emits a lookaround regex for
  `Decimal`.
  - The reader uses JSON mode and puts the schema in the prompt instead. Pydantic validates the reply
    either way.
- **Errors can arrive inside HTTP 200.** Example: `{"error": {"message": "Upstream error from ...",
  "code": 502}}`, with no `choices`. The reader must check for this.
- **429s are common on free models,** which are rate-limited upstream. The error must say so.
- **The `openrouter/free` router is unsafe here.** It picked a content-safety model, which replied
  "User Safety: safe".
- **Free vision models read this blurry image badly.**
  - Qwen 3.8 27B: 24/41 fields correct; it read the chair as 42.50 instead of 250.00.
  - dots-3: 22/41 fields correct; it invented "Organic whole beans".
  - **The checks stopped both:** 4 and 2 arithmetic issues respectively, so both went to review.
  - Descriptions and names are not cross-checked, so only the human check catches errors there.
- **A good default needs a paid model:** `anthropic/claude-sonnet-5.5`, about $2/M input and $10/M
  output, so about 1–2 cents per order. It is configurable with `--model`.

---

### Task 1: OpenRouter reader

**Files:**
- Modify: `pyproject.toml` (add `httpx`), `src/image_to_cash/readers/__init__.py`,
  `src/image_to_cash/readers/base.py` (hide unexpected field names), `tests/test_readers.py`
- Create: `src/image_to_cash/readers/openrouter.py`, `tests/test_openrouter_reader.py`

- [ ] **Step 1: Add the dependency**

Add `"httpx>=0.27",` after the `pydantic` line, so the file becomes:

`pyproject.toml`:

```toml
[project]
name = "image-to-cash"
version = "0.1.0"
description = "Turn a single order image into a verified Order and linked Invoice in Fakturama."
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.8",
    "httpx>=0.27",
    "pillow>=10.4",
    "pyobjc-framework-Vision>=10.3; sys_platform == 'darwin'",
]

[project.scripts]
image-to-cash = "image_to_cash.cli:main"

[dependency-groups]
dev = ["pytest>=8.3", "pytest-cov>=5.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/image_to_cash"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
markers = ["macos: needs macOS system frameworks (Vision, Accessibility)"]
```

Run: `uv lock`
Expected: `Added httpx v0.28.1` (and its dependencies)

- [ ] **Step 2: Write the failing tests**

`tests/test_openrouter_reader.py`:

```python
import base64
import io
import json

import httpx
import pytest
from PIL import Image

from image_to_cash.readers import ReaderError, build_reader
from image_to_cash.readers import openrouter
from image_to_cash.readers.openrouter import API_KEY_ENV, API_URL, DEFAULT_MODEL, OpenRouterReader

API_KEY = "sk-or-v1-test-key-not-real"
MODEL = "vendor/vision-model"
MAX_MESSAGE_LENGTH = 400
ANTHROPIC_IMAGE_LIMIT = 5_000_000


@pytest.fixture
def prepared_image() -> Image.Image:
    return Image.new("RGB", (40, 60), "white")


def reply_with(content: object, finish_reason: str = "stop") -> dict:
    return {"choices": [{"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}]}


def serve(seen: list[httpx.Request] | None = None, *, status: int = 200, **response: object) -> OpenRouterReader:
    """A reader whose HTTP calls go to a fake OpenRouter that answers every request the same way."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, **response)

    return OpenRouterReader(MODEL, API_KEY, transport=httpx.MockTransport(handle))


def failing(error: Exception) -> OpenRouterReader:
    def handle(request: httpx.Request) -> httpx.Response:
        raise error

    return OpenRouterReader(MODEL, API_KEY, transport=httpx.MockTransport(handle))


def uploaded_image(request: httpx.Request) -> tuple[str, Image.Image]:
    url = json.loads(request.content)["messages"][1]["content"][1]["image_url"]["url"]
    header, encoded = url.split(",", 1)
    return header, Image.open(io.BytesIO(base64.b64decode(encoded)))


def reader_error(reader: OpenRouterReader, image: Image.Image) -> ReaderError:
    with pytest.raises(ReaderError) as caught:
        reader.read(image)
    return caught.value


def test_returns_the_order_the_model_transcribed(sample_order, prepared_image):
    reader = serve(json=reply_with(sample_order.model_dump_json()))
    assert reader.read(prepared_image) == sample_order


def test_request_carries_the_model_key_prompt_and_image(sample_order, prepared_image):
    seen: list[httpx.Request] = []
    serve(seen, json=reply_with(sample_order.model_dump_json())).read(prepared_image)
    (request,) = seen
    body = json.loads(request.content)
    assert str(request.url) == API_URL
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert body["model"] == MODEL
    assert body["temperature"] == 0
    assert body["max_tokens"] == openrouter.MAX_OUTPUT_TOKENS
    assert body["response_format"] == {"type": "json_object"}
    assert body["provider"] == {"data_collection": "deny"}
    system_prompt = body["messages"][0]["content"]
    assert "exactly as printed" in system_prompt
    assert '"external_reference"' in system_prompt
    header, image = uploaded_image(request)
    assert header == "data:image/png;base64"
    assert image.size == prepared_image.size


@pytest.mark.parametrize("wrap", ["```json\n{}\n```", "Here is the order:\n{}\nDone.", "  {}  "])
def test_accepts_json_inside_a_code_fence_or_other_words(sample_order, prepared_image, wrap):
    content = wrap.replace("{}", sample_order.model_dump_json())
    assert serve(json=reply_with(content)).read(prepared_image) == sample_order


def test_braces_in_words_after_the_json_fail_closed(sample_order, prepared_image):
    content = sample_order.model_dump_json() + " (see {note})"
    assert "not a valid order" in str(reader_error(serve(json=reply_with(content)), prepared_image))


def test_shrinks_a_large_image_for_upload_and_leaves_the_original_alone(sample_order):
    original = Image.new("RGB", (3000, 1500), "white")
    before = original.tobytes()
    seen: list[httpx.Request] = []
    serve(seen, json=reply_with(sample_order.model_dump_json())).read(original)
    _, uploaded = uploaded_image(seen[0])
    assert uploaded.size == (openrouter.MAX_UPLOAD_LONG_EDGE, openrouter.MAX_UPLOAD_LONG_EDGE // 2)
    assert original.size == (3000, 1500)
    assert original.tobytes() == before


def noise_image(mode: str = "RGB") -> Image.Image:
    return Image.effect_noise((160, 160), 100).convert(mode)


def png_size(image: Image.Image) -> int:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return len(buffer.getvalue())


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "P"])
def test_sends_jpeg_when_the_png_is_too_large(monkeypatch, sample_order, mode):
    image = noise_image(mode)
    monkeypatch.setattr(openrouter, "MAX_UPLOAD_BYTES", png_size(image) - 1)
    seen: list[httpx.Request] = []
    serve(seen, json=reply_with(sample_order.model_dump_json())).read(image)
    header, _ = uploaded_image(seen[0])
    assert header == "data:image/jpeg;base64"


def test_refuses_an_image_too_large_even_as_jpeg(monkeypatch):
    monkeypatch.setattr(openrouter, "MAX_UPLOAD_BYTES", 10)
    seen: list[httpx.Request] = []
    with pytest.raises(ReaderError, match="too large to upload"):
        serve(seen, json={}).read(noise_image())
    assert seen == []


def test_upload_limit_fits_the_strictest_provider_once_base64_encoded():
    assert openrouter.MAX_UPLOAD_BYTES * 4 / 3 < ANTHROPIC_IMAGE_LIMIT


@pytest.mark.parametrize("value", [None, "", "   "])
def test_needs_an_api_key(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(API_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(API_KEY_ENV, value)
    with pytest.raises(ReaderError, match=f"{API_KEY_ENV} is not set"):
        OpenRouterReader.from_env(MODEL)


@pytest.mark.parametrize("key", ["sk-or-v1-abc\ndef", "sk-or-v1-café", "sk-or v1-abc", "sk-or-v1-\x07"])
def test_rejects_a_mangled_api_key_without_echoing_it(monkeypatch, key):
    monkeypatch.setenv(API_KEY_ENV, key)
    with pytest.raises(ReaderError, match="unexpected characters") as caught:
        OpenRouterReader.from_env(MODEL)
    assert "sk-or" not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "rejected the key"),
        (402, "no credit"),
        (404, "no-data-collection"),
        (429, "rate-limited"),
        (500, "HTTP 500"),
        (503, "HTTP 503"),
    ],
)
def test_http_errors_say_what_went_wrong_without_the_key(prepared_image, status, expected):
    payload = {"error": {"message": f"upstream said no to {API_KEY}", "code": status}}
    message = str(reader_error(serve(status=status, json=payload), prepared_image))
    assert expected in message
    assert MODEL in message
    assert "upstream said no to [redacted]" in message
    assert API_KEY not in message


def test_redirects_are_not_followed(prepared_image):
    seen: list[httpx.Request] = []
    reader = serve(seen, status=307, headers={"Location": "https://elsewhere.example/steal"})
    assert "HTTP 307" in str(reader_error(reader, prepared_image))
    assert len(seen) == 1


@pytest.mark.parametrize("body", [b"<html>Bad gateway</html>", b"[" * 100_000], ids=["html", "deeply-nested"])
def test_http_error_without_a_usable_json_body(prepared_image, body):
    assert "HTTP 502" in str(reader_error(serve(status=502, content=body), prepared_image))


def test_upstream_messages_are_capped(prepared_image):
    cap = openrouter.MAX_UPSTREAM_MESSAGE
    message = str(reader_error(serve(status=400, json={"error": {"message": "x" * 5000}}), prepared_image))
    assert "x" * cap in message
    assert "x" * (cap + 1) not in message


def test_the_cap_never_leaves_part_of_the_key(prepared_image):
    upstream = "x" * (openrouter.MAX_UPSTREAM_MESSAGE - 5) + API_KEY
    message = str(reader_error(serve(status=400, json={"error": {"message": upstream}}), prepared_image))
    assert "sk-or" not in message


def test_a_key_split_by_control_characters_is_still_redacted(prepared_image):
    upstream = f"bad key {API_KEY[:5]}\x1b{API_KEY[5:]}"
    message = str(reader_error(serve(status=400, json={"error": {"message": upstream}}), prepared_image))
    assert "bad key [redacted]" in message


def test_upstream_messages_are_one_printable_line(prepared_image):
    upstream = "bad\x1b[2J\x1b]0;title\x07\nerror: forged line"
    message = str(reader_error(serve(status=400, json={"error": {"message": upstream}}), prepared_image))
    assert "\x1b" not in message
    assert "\x07" not in message
    assert "\n" not in message


def test_an_error_inside_a_200_reply_is_reported_without_the_key(prepared_image):
    payload = {"error": {"message": f"Upstream error from Nvidia: bad key {API_KEY}", "code": 502}}
    message = str(reader_error(serve(json=payload), prepared_image))
    assert "Upstream error from Nvidia" in message
    assert API_KEY not in message


def test_an_error_attached_to_the_choice_is_reported(prepared_image):
    payload = {"choices": [{"finish_reason": "error", "error": {"message": "provider blew up"}, "message": {}}]}
    assert "failed: provider blew up" in str(reader_error(serve(json=payload), prepared_image))


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": ["text"]}, [], "text"])
def test_a_reply_without_choices_is_rejected(prepared_image, payload):
    assert "no choices" in str(reader_error(serve(json=payload), prepared_image))


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", b"[" * 100_000], ids=["html", "deeply-nested"])
def test_a_reply_that_is_not_json_is_rejected(prepared_image, body):
    assert "not JSON" in str(reader_error(serve(content=body), prepared_image))


def test_a_reply_cut_off_at_the_token_limit_is_rejected(sample_order, prepared_image):
    content = sample_order.model_dump_json()[:100]
    assert "cut off" in str(reader_error(serve(json=reply_with(content, finish_reason="length")), prepared_image))


@pytest.mark.parametrize("content", [None, "", "   ", 42])
def test_an_empty_reply_is_rejected(prepared_image, content):
    assert "empty reply" in str(reader_error(serve(json=reply_with(content)), prepared_image))


def test_a_message_that_is_not_an_object_counts_as_empty(prepared_image):
    payload = {"choices": [{"finish_reason": "stop", "message": "text"}]}
    assert "empty reply" in str(reader_error(serve(json=payload), prepared_image))


def test_an_empty_reply_names_an_unusual_finish_reason(prepared_image):
    reply = reply_with("", finish_reason="tool_calls")
    assert "empty reply (finish_reason: tool_calls)" in str(reader_error(serve(json=reply), prepared_image))


def test_an_unusual_finish_reason_is_cleaned_and_capped(prepared_image):
    message = str(reader_error(serve(json=reply_with("", finish_reason="x" * 100 + API_KEY)), prepared_image))
    assert "x" * 40 in message
    assert "x" * 41 not in message
    assert "sk-or" not in message


@pytest.mark.parametrize("finish_reason", ["content_filter", "error"])
def test_a_model_that_stopped_early_is_reported_even_with_partial_content(prepared_image, finish_reason):
    reply = reply_with('{"external_ref', finish_reason=finish_reason)
    message = str(reader_error(serve(json=reply), prepared_image))
    assert f"stopped early (finish_reason: {finish_reason})" in message


@pytest.mark.parametrize(
    "content",
    [
        "Sorry, SECRET-VALUE is unreadable",
        '{"external_reference": "SECRET-VALUE"}',
        '{"SECRET-VALUE, +49 170 1234567": 1}',
        "[]",
    ],
)
def test_a_reply_that_is_not_a_valid_order_is_rejected_without_echoing_it(prepared_image, content):
    message = str(reader_error(serve(json=reply_with(content)), prepared_image))
    assert "not a valid order" in message
    assert "SECRET-VALUE" not in message
    assert len(message) < MAX_MESSAGE_LENGTH


def test_network_failures_become_reader_errors_without_the_key(prepared_image):
    leaky = httpx.LocalProtocolError(f"Illegal header value b'Bearer {API_KEY}'")
    error = reader_error(failing(leaky), prepared_image)
    assert "cannot reach OpenRouter" in str(error)
    assert API_KEY not in str(error)
    assert error.__cause__ is None
    assert error.__suppress_context__


def test_connection_failures_say_so(prepared_image):
    error = reader_error(failing(httpx.ConnectError("name resolution failed")), prepared_image)
    assert "cannot reach OpenRouter: name resolution failed" in str(error)


def test_a_read_timeout_warns_that_the_request_may_be_billed(prepared_image):
    error = reader_error(failing(httpx.ReadTimeout("")), prepared_image)
    assert "no reply from OpenRouter within" in str(error)
    assert "may still be billed" in str(error)


@pytest.mark.parametrize("timeout", [httpx.ConnectTimeout(""), httpx.WriteTimeout(""), httpx.PoolTimeout("")])
def test_other_timeouts_say_the_request_never_got_through(prepared_image, timeout):
    message = str(reader_error(failing(timeout), prepared_image))
    assert f"cannot reach OpenRouter: {type(timeout).__name__}" in message
    assert "billed" not in message


def test_build_reader_uses_the_default_model_and_the_key_from_the_environment(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    assert build_reader("openrouter").model == DEFAULT_MODEL
    assert build_reader("openrouter", model=MODEL).model == MODEL


def test_build_reader_rejects_a_fixture_for_openrouter(monkeypatch, sample_order_path):
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    with pytest.raises(ValueError, match="--fixture only applies"):
        build_reader("openrouter", fixture=sample_order_path)


def test_build_reader_rejects_a_model_for_the_fixture_reader(sample_order_path):
    with pytest.raises(ValueError, match="--model only applies"):
        build_reader("fixture", fixture=sample_order_path, model=MODEL)
```

`describe_validation_error` must also stop echoing the names of unexpected fields, because a model's
reply controls them. Append one test to `tests/test_readers.py`, which becomes:

`tests/test_readers.py`:

```python
import json

import pytest
from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order
from image_to_cash.readers import ReaderError, build_reader
from image_to_cash.readers.base import MAX_ISSUES_SHOWN, describe_validation_error

MAX_MESSAGE_LENGTH = 600


@pytest.fixture
def prepared_image() -> Image.Image:
    return Image.new("RGB", (40, 60), "white")


def test_fixture_reader_replays_recorded_order(sample_order_path, prepared_image, sample_order):
    reader = build_reader("fixture", fixture=sample_order_path)
    assert reader.read(prepared_image) == sample_order


def test_fixture_reader_reads_the_path_it_was_given(tmp_path, prepared_image, sample_order):
    other = tmp_path / "other.json"
    other_order = sample_order.model_copy(update={"external_reference": "OTHER-1"})
    other.write_text(other_order.model_dump_json(), encoding="utf-8")
    assert build_reader("fixture", fixture=other).read(prepared_image).external_reference == "OTHER-1"


def test_fixture_reader_requires_a_path():
    with pytest.raises(ValueError, match="--fixture"):
        build_reader("fixture")


def test_unknown_reader_is_rejected():
    with pytest.raises(ValueError, match="unknown image reader"):
        build_reader("nope")


def test_missing_fixture_raises_reader_error(tmp_path, prepared_image):
    reader = build_reader("fixture", fixture=tmp_path / "missing.json")
    with pytest.raises(ReaderError, match="missing.json"):
        reader.read(prepared_image)


def test_non_utf8_fixture_raises_reader_error(tmp_path, prepared_image):
    latin1 = tmp_path / "latin1.json"
    latin1.write_bytes(b'{"external_reference": "\xe9"}')
    with pytest.raises(ReaderError, match="latin1.json"):
        build_reader("fixture", fixture=latin1).read(prepared_image)


@pytest.mark.parametrize("content", ["", "{not json", "[]", '{"surprise": 1}', '{"external_reference": "X"}'])
def test_invalid_fixture_raises_a_short_reader_error(tmp_path, prepared_image, content):
    bad = tmp_path / "bad.json"
    bad.write_text(content, encoding="utf-8")
    with pytest.raises(ReaderError, match="bad.json") as caught:
        build_reader("fixture", fixture=bad).read(prepared_image)
    assert len(str(caught.value)) < MAX_MESSAGE_LENGTH


def test_invalid_fixture_message_omits_the_offending_value(tmp_path, prepared_image, sample_order):
    fixture = tmp_path / "order.json"
    recorded = sample_order.model_dump(mode="json") | {"order_date": "SECRET-VALUE"}
    fixture.write_text(json.dumps(recorded), encoding="utf-8")
    with pytest.raises(ReaderError, match="order_date") as caught:
        build_reader("fixture", fixture=fixture).read(prepared_image)
    assert "SECRET-VALUE" not in str(caught.value)


def test_validation_summary_lists_a_few_problems_and_counts_the_rest():
    with pytest.raises(ValidationError) as caught:
        Order.model_validate({})
    hidden = len(caught.value.errors()) - MAX_ISSUES_SHOWN
    summary = describe_validation_error(caught.value)
    assert hidden > 0
    assert summary.count(";") == MAX_ISSUES_SHOWN - 1
    assert summary.endswith(f"(+{hidden} more)")


def test_validation_summary_hides_the_names_of_unexpected_fields(sample_order):
    recorded = sample_order.model_dump(mode="json")
    customer = recorded["customer"] | {"Max SECRET-NAME, +49 170 1234567": 1}
    with pytest.raises(ValidationError) as caught:
        Order.model_validate(recorded | {"customer": customer})
    summary = describe_validation_error(caught.value)
    assert summary.startswith("customer.<unexpected field>: ")
    assert "SECRET-NAME" not in summary
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_openrouter_reader.py tests/test_readers.py -q`
Expected:
- a collection error for `test_openrouter_reader.py`:
  `ImportError: cannot import name 'openrouter' from 'image_to_cash.readers'`;
- `test_validation_summary_hides_the_names_of_unexpected_fields` fails.

- [ ] **Step 4: Write the reader**

`src/image_to_cash/readers/openrouter.py`:

```python
"""Reads an order image with a vision model through OpenRouter's chat-completions API."""

from __future__ import annotations

import base64
import io
import json
import os

import httpx
from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order
from image_to_cash.readers.base import ReaderError, describe_validation_error

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY_ENV = "OPENROUTER_API_KEY"
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
TIMEOUT_SECONDS = 120.0
# An order reply is about 400 tokens plus 65 per line. OpenRouter reserves credit for the whole cap,
# so a generous cap can fail a request the account could afford.
MAX_OUTPUT_TOKENS = 3000
MAX_UPLOAD_LONG_EDGE = 2048
MAX_UPLOAD_BYTES = 3_700_000  # about 4.9 MB once base64-encoded; Anthropic's per-image limit is 5 MB
JPEG_QUALITY = 90
MAX_UPSTREAM_MESSAGE = 200
REDACTED = "[redacted]"

# JSON mode plus the schema in the prompt, not the provider's schema-constrained decoding:
# constrained decoders reject the lookaround regex Pydantic emits for Decimal fields.
# The reply is validated against `Order` either way.
SYSTEM_PROMPT = (
    "You transcribe one sales order image into a JSON object that matches the JSON Schema below.\n"
    "Rules:\n"
    "- Copy every value exactly as printed. Never compute, round, correct or complete anything.\n"
    '- Dates as YYYY-MM-DD. Money and quantities as decimal strings with a dot, e.g. "250.00".\n'
    '- Percentages as decimal strings without the % sign, e.g. "19".\n'
    "- If a value is hard to read, give your best reading; never leave a required field empty.\n"
    "- Use null only for optional fields that are not printed.\n"
    "Reply with the JSON object only.\n\n"
    "JSON Schema:\n" + json.dumps(Order.model_json_schema())
)

# Orders carry customers' personal data: only route to providers that declare they neither store nor
# train on prompts.
PROVIDER_PREFERENCES = {"data_collection": "deny"}
# Finish reasons that mean the model stopped before finishing its answer.
STOPPED_EARLY = ("content_filter", "error")

STATUS_HINTS = {
    401: f"OpenRouter rejected the key in {API_KEY_ENV}",
    402: "the OpenRouter account has no credit for this model",
    404: "unknown model, or none of its providers meets the no-data-collection policy",
    429: "rate-limited; retry shortly",
}


class OpenRouterReader:
    def __init__(self, model: str, api_key: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if not _usable_key(api_key):
            raise ReaderError(f"{API_KEY_ENV} has unexpected characters; copy the key again")
        self._model = model
        self._api_key = api_key
        self._transport = transport

    @classmethod
    def from_env(cls, model: str) -> OpenRouterReader:
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            raise ReaderError(f"{API_KEY_ENV} is not set; put it in .env and run with `uv run --env-file .env`")
        return cls(model, api_key)

    @property
    def model(self) -> str:
        return self._model

    def read(self, image: Image.Image) -> Order:
        reply = self._post(_request_body(self._model, _data_url(image)))
        return _parse_order(self._model, self._reply_text(reply))

    def _post(self, body: dict[str, object]) -> object:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_SECONDS) as client:
                response = client.post(API_URL, json=body, headers=headers)
        except httpx.ReadTimeout as error:
            message = f"no reply from OpenRouter within {TIMEOUT_SECONDS:.0f} s; the request may still be billed"
            raise ReaderError(message) from error
        except httpx.TimeoutException as error:  # connect, write or pool: the request was never processed
            message = f"cannot reach OpenRouter: {type(error).__name__} after {TIMEOUT_SECONDS:.0f} s"
            raise ReaderError(message) from error
        except httpx.HTTPError as error:
            detail = self._clean(str(error)) or type(error).__name__
            raise ReaderError(f"cannot reach OpenRouter: {detail}") from None  # the cause may quote headers
        if response.status_code != httpx.codes.OK:
            raise ReaderError(self._status_message(response))
        reply = _json_or_none(response)
        if reply is None:
            raise ReaderError("OpenRouter's reply is not JSON")
        return reply

    def _status_message(self, response: httpx.Response) -> str:
        message = f"OpenRouter returned HTTP {response.status_code} for {self._model}"
        hint = STATUS_HINTS.get(response.status_code)
        if hint:
            message += f": {hint}"
        upstream = self._upstream_message(_json_or_none(response))
        if upstream:
            message += f" ({upstream})"
        return message

    def _reply_text(self, reply: object) -> str:
        upstream = self._upstream_message(reply)
        if upstream:  # OpenRouter reports some upstream failures inside an HTTP 200 reply
            raise ReaderError(f"OpenRouter could not run {self._model}: {upstream}")
        choices = reply.get("choices") if isinstance(reply, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ReaderError(f"OpenRouter's reply for {self._model} has no choices")
        choice = choices[0]
        upstream = self._upstream_message(choice)
        if upstream:
            raise ReaderError(f"{self._model} failed: {upstream}")
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise ReaderError(f"{self._model}'s reply was cut off at {MAX_OUTPUT_TOKENS} tokens")
        if finish_reason in STOPPED_EARLY:
            raise ReaderError(f"{self._model} stopped early (finish_reason: {finish_reason})")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            reason = f" (finish_reason: {self._clean(str(finish_reason))[:40]})" if finish_reason else ""
            raise ReaderError(f"{self._model} returned an empty reply{reason}")
        return content

    def _upstream_message(self, payload: object) -> str:
        """The `error.message` in an OpenRouter payload: one printable line, key removed, then capped."""
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        return self._clean(str(message))[:MAX_UPSTREAM_MESSAGE] if message else ""

    def _clean(self, text: str) -> str:
        """One line of printable characters, with the API key replaced: safe to print to a terminal."""
        printable = "".join(character for character in text if character.isprintable() or character.isspace())
        return " ".join(printable.split()).replace(self._api_key, REDACTED)


def _usable_key(api_key: str) -> bool:
    return bool(api_key) and api_key.isascii() and api_key.isprintable() and not any(c.isspace() for c in api_key)


def _json_or_none(response: httpx.Response) -> object:
    try:
        return response.json()
    except (ValueError, RecursionError):  # deep nesting overflows the JSON parser
        return None


def _data_url(image: Image.Image) -> str:
    encoded, mime = _encode(_fit(image))
    return f"data:{mime};base64,{base64.b64encode(encoded).decode('ascii')}"


def _fit(image: Image.Image) -> Image.Image:
    """`image` if its long edge is at most MAX_UPLOAD_LONG_EDGE, else a shrunk copy; never modifies it."""
    scale = MAX_UPLOAD_LONG_EDGE / max(image.size)
    if scale >= 1:
        return image
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _encode(image: Image.Image) -> tuple[bytes, str]:
    png = _save(image, "PNG")
    if len(png) <= MAX_UPLOAD_BYTES:
        return png, "image/png"
    jpeg = _save(image.convert("RGB"), "JPEG", quality=JPEG_QUALITY)
    if len(jpeg) <= MAX_UPLOAD_BYTES:
        return jpeg, "image/jpeg"
    raise ReaderError(f"image is too large to upload: {len(jpeg)} bytes as JPEG, limit {MAX_UPLOAD_BYTES}")


def _save(image: Image.Image, image_format: str, **options: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


def _request_body(model: str, data_url: str) -> dict[str, object]:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
        "provider": dict(PROVIDER_PREFERENCES),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this order."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }


def _parse_order(model: str, text: str) -> Order:
    try:
        return Order.model_validate_json(_json_object_text(text))
    except ValidationError as error:
        problems = describe_validation_error(error)
        raise ReaderError(f"{model}'s reply is not a valid order: {problems}") from error


def _json_object_text(text: str) -> str:
    """The text from the first `{` to the last `}`: drops code fences and any words around the JSON."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text
```

And hide unexpected field names in the validation summary:

`src/image_to_cash/readers/base.py`:

```python
"""Image-reader interface: any provider turns an order image into a schema-valid Order."""

from __future__ import annotations

from typing import Protocol

from PIL import Image
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from image_to_cash.model import Order

MAX_ISSUES_SHOWN = 5
UNEXPECTED_FIELD = "<unexpected field>"


class ReaderError(RuntimeError):
    """The image reader could not produce a schema-valid Order."""


class ImageReader(Protocol):
    def read(self, image: Image.Image) -> Order:
        """Read an image already prepared by `imaging`: upright, RGB and upscaled.

        Must not modify `image` (copy it before resizing). Raises ReaderError when it cannot
        produce a schema-valid Order.
        """
        ...


def describe_validation_error(error: ValidationError) -> str:
    """A one-line summary of the first few problems, without the offending values.

    The values are left out because a reader's output can hold personal data. So are the names of
    unexpected fields, which a model's reply controls too.
    """
    issues = error.errors(include_url=False, include_context=False, include_input=False)
    shown = "; ".join(f"{_location(issue)}: {issue['msg']}" for issue in issues[:MAX_ISSUES_SHOWN])
    hidden = len(issues) - MAX_ISSUES_SHOWN
    return f"{shown} (+{hidden} more)" if hidden > 0 else shown


def _location(issue: ErrorDetails) -> str:
    loc = issue["loc"]
    if issue["type"] == "extra_forbidden":
        loc = (*loc[:-1], UNEXPECTED_FIELD)
    return ".".join(str(part) for part in loc) or "<document>"
```

- [ ] **Step 5: Register it in `build_reader`**

`src/image_to_cash/readers/__init__.py`:

```python
"""Image readers behind one interface; `build_reader` picks one by name."""

from __future__ import annotations

from pathlib import Path

from image_to_cash.readers.base import ImageReader, ReaderError
from image_to_cash.readers.fixture import FixtureReader
from image_to_cash.readers.openrouter import DEFAULT_MODEL, OpenRouterReader

READERS = ("fixture", "openrouter")


def build_reader(name: str, *, fixture: Path | None = None, model: str | None = None) -> ImageReader:
    if name == "fixture":
        if fixture is None:
            raise ValueError("the fixture reader needs --fixture PATH")
        if model is not None:
            raise ValueError("--model only applies to --reader openrouter")
        return FixtureReader(fixture)
    if name == "openrouter":
        if fixture is not None:
            raise ValueError("--fixture only applies to --reader fixture")
        return OpenRouterReader.from_env(DEFAULT_MODEL if model is None else model)
    raise ValueError(f"unknown image reader: {name!r} (available: {', '.join(READERS)})")


__all__ = ["READERS", "FixtureReader", "ImageReader", "OpenRouterReader", "ReaderError", "build_reader"]
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_openrouter_reader.py tests/test_readers.py -q`
Expected: `78 passed` (64 + 14)

Run: `uv run pytest -q`
Expected: 234 passed (169 + 1 + 64)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/image_to_cash/readers/ tests/test_openrouter_reader.py tests/test_readers.py
git commit -m "feat: add OpenRouter vision reader"
```

---

### Task 2: `--reader openrouter` and `--model` on the command line

**Files:**
- Modify: `src/image_to_cash/cli.py`, `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append four tests to `tests/test_cli.py`, and import `httpx`, `OpenRouterReader`, `ReaderError`,
`API_KEY_ENV` and `DEFAULT_MODEL`. The whole file becomes:

`tests/test_cli.py`:

```python
import json
from decimal import Decimal

import httpx
import pytest

from image_to_cash import cli
from image_to_cash.readers import OpenRouterReader, ReaderError
from image_to_cash.readers.openrouter import API_KEY_ENV, DEFAULT_MODEL


@pytest.fixture
def use_ocr(monkeypatch):
    def install(fake):
        monkeypatch.setattr(cli, "build_ocr", lambda name: fake)

    return install


def run_extract(order_image, sample_order_path, out_dir):
    return cli.main(
        ["extract", str(order_image), "--fixture", str(sample_order_path), "--out", str(out_dir)]
    )


def test_extract_clean_writes_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything
):
    use_ocr(ocr_seeing_everything)
    assert run_extract(order_image, sample_order_path, tmp_path) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()


def test_extract_unconfirmed_writes_review(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku
):
    use_ocr(ocr_missing_first_sku)
    assert run_extract(order_image, sample_order_path, tmp_path) == cli.EXIT_REVIEW
    assert (tmp_path / "review.json").is_file()


def test_approve_turns_review_draft_into_order(tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path / "x")
    code = cli.main(["approve", str(tmp_path / "x" / "review.json"), "--out", str(tmp_path / "ok")])
    assert code == cli.EXIT_OK
    order = json.loads((tmp_path / "ok" / "order.json").read_text())
    assert order["external_reference"] == "WEB-2026-0714-A17"


def test_approve_refuses_draft_that_breaks_invariants(tmp_path, sample_order):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("1.00")})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"totals": totals}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert not (tmp_path / "ok" / "order.json").exists()


def test_missing_image_is_a_clear_error(tmp_path, sample_order_path, capsys):
    code = run_extract(tmp_path / "missing.png", sample_order_path, tmp_path)
    assert code == cli.EXIT_ERROR
    assert "image not found" in capsys.readouterr().err


def test_failed_extract_removes_an_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path)
    assert run_extract(order_image, tmp_path / "missing.json", tmp_path) == cli.EXIT_ERROR
    assert not (tmp_path / "order.json").exists()


def test_refused_approve_removes_an_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, sample_order
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path / "out")
    totals = sample_order.totals.model_copy(update={"gross": Decimal("1.00")})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"totals": totals}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "out")]) == cli.EXIT_REVIEW
    assert not (tmp_path / "out" / "order.json").exists()


def test_invalid_draft_is_refused_briefly_without_echoing_values(tmp_path, sample_order, capsys):
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(sample_order.model_dump(mode="json") | {"order_date": "SECRET-VALUE"}))
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    error = capsys.readouterr().err
    assert "order_date" in error
    assert "SECRET-VALUE" not in error


def test_approve_refuses_an_ambiguous_contact_name(tmp_path, sample_order, capsys):
    customer = sample_order.customer.model_copy(update={"contact_name": "Anna Maria Klein"})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"customer": customer}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert "contact_name_ambiguous" in capsys.readouterr().err
    assert not (tmp_path / "ok" / "order.json").exists()


def test_approve_refuses_a_draft_that_is_not_an_object(tmp_path, capsys):
    draft = tmp_path / "draft.json"
    draft.write_text("[]")
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert "not approved" in capsys.readouterr().err


def test_approve_in_the_extract_folder_keeps_the_review_as_a_record(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    assert cli.main(["approve", str(tmp_path / "review.json"), "--out", str(tmp_path)]) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()
    assert (tmp_path / "review.json").is_file()


def test_approve_refuses_order_json_as_a_draft_and_keeps_it(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, capsys
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path)
    assert cli.main(["approve", str(tmp_path / "order.json"), "--out", str(tmp_path)]) == cli.EXIT_ERROR
    assert "Stage 2's input" in capsys.readouterr().err
    assert (tmp_path / "order.json").is_file()


def test_help_lists_the_exit_codes(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    help_text = " ".join(capsys.readouterr().out.split())  # argparse wraps to the terminal width
    assert "3 needs review" in help_text


def test_exit_codes_are_the_documented_contract():
    assert (cli.EXIT_OK, cli.EXIT_ERROR, cli.EXIT_REVIEW) == (0, 1, 3)


def test_usage_error_exits_2():
    with pytest.raises(SystemExit) as stop:
        cli.main(["extract"])
    assert stop.value.code == 2


def test_review_message_names_the_next_step(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku, capsys
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    out = capsys.readouterr().out
    assert "needs review: 1 unconfirmed field(s), 0 issue(s)" in out
    assert f"image-to-cash approve {tmp_path / 'review.json'}" in out


def test_approve_says_what_it_approved(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku, capsys
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    capsys.readouterr()
    assert cli.main(["approve", str(tmp_path / "review.json"), "--out", str(tmp_path)]) == cli.EXIT_OK
    approved = "approved WEB-2026-0714-A17: Northstar Office GmbH, 2 line(s), gross 678.30 EUR, PAID"
    assert approved in capsys.readouterr().out


@pytest.mark.parametrize("draft_name", ["missing.json", "binary.json", "broken.json"])
def test_unreadable_draft_leaves_no_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, draft_name
):
    use_ocr(ocr_seeing_everything)
    out = tmp_path / "out"
    run_extract(order_image, sample_order_path, out)
    (tmp_path / "binary.json").write_bytes(b"\x89PNG\xff")
    (tmp_path / "broken.json").write_text("{oops")
    assert cli.main(["approve", str(tmp_path / draft_name), "--out", str(out)]) != cli.EXIT_OK
    assert not (out / "order.json").exists()


def test_broken_json_draft_names_the_file(tmp_path, capsys):
    draft = tmp_path / "review.json"
    draft.write_text('{"draft_order": {},}')
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert f"{draft} is not valid JSON" in capsys.readouterr().err


def test_openrouter_without_a_key_is_a_clear_error(tmp_path, order_image, monkeypatch, capsys):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    argv = ["extract", str(order_image), "--reader", "openrouter", "--out", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert API_KEY_ENV in capsys.readouterr().err


def test_extract_passes_the_model_to_the_reader(tmp_path, order_image, monkeypatch):
    requested = {}

    def build_reader(name, *, fixture=None, model=None):
        requested.update(name=name, fixture=fixture, model=model)
        raise ReaderError("stop before reading")

    monkeypatch.setattr(cli, "build_reader", build_reader)
    argv = ["extract", str(order_image), "--reader", "openrouter", "--model", "vendor/model", "--out", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert requested == {"name": "openrouter", "fixture": None, "model": "vendor/model"}


def test_extract_with_openrouter_writes_order(
    tmp_path, order_image, sample_order, monkeypatch, use_ocr, ocr_seeing_everything
):
    reply = {"choices": [{"finish_reason": "stop", "message": {"content": sample_order.model_dump_json()}}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=reply))
    reader = OpenRouterReader("vendor/model", "test-key", transport=transport)
    monkeypatch.setattr(cli, "build_reader", lambda name, **options: reader)
    use_ocr(ocr_seeing_everything)
    argv = ["extract", str(order_image), "--reader", "openrouter", "--out", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()


def test_extract_help_names_the_default_model(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["extract", "--help"])
    assert exit_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "--model" in help_text
    assert DEFAULT_MODEL in help_text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: 2 failed (`test_extract_passes_the_model_to_the_reader` and
`test_extract_help_names_the_default_model`: no `--model` option yet), the rest pass.

- [ ] **Step 3: Add `--model` and pass it to `build_reader`**

The whole file becomes:

`src/image_to_cash/cli.py`:

```python
"""Command line: `image-to-cash extract IMAGE` and `image-to-cash approve DRAFT`."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from pydantic import ValidationError

from image_to_cash.errors import NeedsReview
from image_to_cash.extract import extract
from image_to_cash.invariants import check_invariants
from image_to_cash.model import Order
from image_to_cash.normalized import normalize
from image_to_cash.ocr import ENGINES, OcrError, build_ocr
from image_to_cash.outputs import ORDER_FILE, clear_results, discard_order, write_order, write_result
from image_to_cash.readers import READERS, ReaderError, build_reader
from image_to_cash.readers.base import describe_validation_error
from image_to_cash.readers.openrouter import DEFAULT_MODEL

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REVIEW = 3  # 2 is argparse's code for bad command-line usage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-to-cash",
        description="Read an order image into order.json for Stage 2, or review.json for a person.",
        epilog="exit codes: 0 order.json written, 1 error, 2 bad usage, 3 needs review",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    extract_cmd = commands.add_parser("extract", help="read an order image into order.json")
    extract_cmd.add_argument("image", type=Path)
    extract_cmd.add_argument("--reader", default="fixture", choices=READERS)
    extract_cmd.add_argument("--fixture", type=Path, help="recorded response for --reader fixture")
    extract_cmd.add_argument(
        "--model", help=f"OpenRouter model for --reader openrouter (default {DEFAULT_MODEL})"
    )
    extract_cmd.add_argument("--ocr", default="macos-vision", choices=ENGINES)
    extract_cmd.add_argument(
        "--out", type=Path, default=Path("out"), help="result folder; cleared of order.json and review.json first"
    )

    approve_cmd = commands.add_parser(
        "approve", help="turn a human-corrected draft (review.json or order JSON) into order.json"
    )
    approve_cmd.add_argument("draft", type=Path)
    approve_cmd.add_argument(
        "--out", type=Path, default=Path("out"), help="folder for order.json; an earlier one is removed first"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            return _extract(args)
        return _approve(args)
    except (ReaderError, OcrError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def _extract(args: argparse.Namespace) -> int:
    clear_results(args.out)  # a failed run must not leave an earlier order for Stage 2
    if not args.image.is_file():
        raise FileNotFoundError(f"image not found or not a file: {args.image}")
    reader = build_reader(args.reader, fixture=args.fixture, model=args.model)
    result = extract(args.image, reader, build_ocr(args.ocr))
    target = write_result(result, args.out)
    if result.needs_review:
        print(
            f"needs review: {len(result.mismatches)} unconfirmed field(s), "
            f"{len(result.issues)} issue(s); see {target}"
        )
        print(f"  check every field of draft_order against {result.source_image}, correct it, then run:")
        print(f"  image-to-cash approve {shlex.quote(str(target))} --out {shlex.quote(str(args.out))}")
        return EXIT_REVIEW
    print(f"order written to {target}")
    return EXIT_OK


def _approve(args: argparse.Namespace) -> int:
    if args.draft.resolve() == (args.out / ORDER_FILE).resolve():
        raise ValueError(f"{args.draft} is Stage 2's input, not a draft; approve review.json instead")
    discard_order(args.out)  # any outcome but "approved" must leave no earlier order for Stage 2
    draft = args.draft.read_text(encoding="utf-8")
    try:
        payload = json.loads(draft)
    except json.JSONDecodeError as error:
        print(f"not approved: {args.draft} is not valid JSON: {error}", file=sys.stderr)
        return EXIT_REVIEW
    candidate = payload.get("draft_order", payload) if isinstance(payload, dict) else payload
    try:
        order = Order.model_validate(candidate)
    except ValidationError as error:
        print(f"not approved: draft is not a valid order: {describe_validation_error(error)}", file=sys.stderr)
        return EXIT_REVIEW
    issues = check_invariants(order)
    if issues:
        for issue in issues:
            print(f"not approved: {issue.code}: {issue.message}", file=sys.stderr)
        return EXIT_REVIEW
    try:
        normalized = normalize(order)
    except NeedsReview as review:
        print(f"not approved: {review}", file=sys.stderr)
        return EXIT_REVIEW
    target = write_order(normalized, args.out)
    print(
        f"approved {normalized.external_reference}: {normalized.debtor.company}, "
        f"{len(normalized.lines)} line(s), gross {normalized.totals.gross} {order.currency}, "
        f"{normalized.payment.status.value}"
    )
    print(f"order written to {target}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: 238 passed

- [ ] **Step 5: Commit**

```bash
git add src/image_to_cash/cli.py tests/test_cli.py
git commit -m "feat: choose the OpenRouter reader and model from the command line"
```

---

### Task 3: Design doc

**Files:**
- Modify: `docs/DESIGN.md`

- [ ] **Step 1: Name OpenRouter among the image-reader adapters**

In the *Image reader* bullet (§3), after "Document AI Custom Extractor", add OpenRouter. It is one key
for many vendors, and it is the adapter this build ships. State that it uses JSON mode with the schema
in the prompt, not schema-constrained decoding, and why (the spike finding above).

- [ ] **Step 2: Note the free-model finding in the trade-offs table**

In the "Vision LLM + OCR + arithmetic" row, add that free vision models misread the blurry sample badly
but were stopped by the checks, and that names and descriptions are only checked by a person.

- [ ] **Step 3: Commit**

```bash
git add docs/DESIGN.md
git commit -m "docs: OpenRouter reader in the design"
```

---

### Task 4: Live run on the supplied image (needs OpenRouter credit)

**Files:**
- Modify: `docs/extraction-run-notes.md`

- [ ] **Step 1: Run the live reader**

Run: `uv run --env-file .env image-to-cash extract samples/sales-order-input.png --reader openrouter --out out/live`
Expected: exit 3 (needs review). OCR confirms the same 4 fields as before, and there are 0 or more
arithmetic issues.

- [ ] **Step 2: Compare the model's draft with the fixture, field by field**

Record:
- the model;
- how many of the 41 leaf fields match `tests/fixtures/sample_order.json`;
- every field that differs, and whether the checks or only the human check would catch it.

- [ ] **Step 3: Add a "Live reader" section to `docs/extraction-run-notes.md` and commit**

```bash
git add docs/extraction-run-notes.md
git commit -m "docs: record the live OpenRouter run on the supplied image"
```
