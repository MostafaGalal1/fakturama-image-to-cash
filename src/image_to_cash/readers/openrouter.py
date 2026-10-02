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
