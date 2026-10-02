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
MAX_OUTPUT_TOKENS = 8192
MAX_UPLOAD_LONG_EDGE = 2048
MAX_UPLOAD_BYTES = 3_700_000  # about 4.9 MB once base64-encoded; Anthropic's per-image limit is 5 MB
JPEG_QUALITY = 90
MAX_UPSTREAM_MESSAGE = 200

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

STATUS_HINTS = {
    401: f"OpenRouter rejected the key in {API_KEY_ENV}",
    402: "the OpenRouter account has no credit for this model; add credit or pick a ':free' model with --model",
    429: "rate-limited; retry shortly or pick another model with --model",
}


class OpenRouterReader:
    def __init__(self, model: str, api_key: str, *, transport: httpx.BaseTransport | None = None) -> None:
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
        return _parse_order(self._model, _reply_text(self._model, reply))

    def _post(self, body: dict) -> object:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_SECONDS) as client:
                response = client.post(API_URL, json=body, headers=headers)
        except httpx.HTTPError as error:
            raise ReaderError(f"cannot reach OpenRouter: {str(error) or type(error).__name__}") from error
        if response.status_code != httpx.codes.OK:
            raise ReaderError(self._status_message(response))
        try:
            return response.json()
        except ValueError as error:
            raise ReaderError("OpenRouter's reply is not JSON") from error

    def _status_message(self, response: httpx.Response) -> str:
        message = f"OpenRouter returned HTTP {response.status_code} for {self._model}"
        hint = STATUS_HINTS.get(response.status_code)
        if hint:
            message += f": {hint}"
        try:
            upstream = _upstream_message(response.json())
        except ValueError:
            upstream = ""
        if upstream:
            message += f" ({upstream})"
        return message.replace(self._api_key, "[redacted]")


def _data_url(image: Image.Image) -> str:
    encoded, mime = _encode(_fit(image))
    return f"data:{mime};base64,{base64.b64encode(encoded).decode('ascii')}"


def _fit(image: Image.Image) -> Image.Image:
    """A copy no longer than MAX_UPLOAD_LONG_EDGE on its long edge; `image` itself is left alone."""
    scale = MAX_UPLOAD_LONG_EDGE / max(image.size)
    if scale >= 1:
        return image
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _encode(image: Image.Image) -> tuple[bytes, str]:
    png = _save(image, "PNG")
    if len(png) <= MAX_UPLOAD_BYTES:
        return png, "image/png"
    jpeg = _save(image, "JPEG", quality=JPEG_QUALITY)
    if len(jpeg) <= MAX_UPLOAD_BYTES:
        return jpeg, "image/jpeg"
    raise ReaderError(f"image is too large to upload: {len(jpeg)} bytes as JPEG, limit {MAX_UPLOAD_BYTES}")


def _save(image: Image.Image, image_format: str, **options: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


def _request_body(model: str, data_url: str) -> dict:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
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


def _reply_text(model: str, reply: object) -> str:
    upstream = _upstream_message(reply)
    if upstream:  # OpenRouter reports some upstream failures inside an HTTP 200 reply
        raise ReaderError(f"OpenRouter could not run {model}: {upstream}")
    choices = reply.get("choices") if isinstance(reply, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ReaderError(f"OpenRouter's reply for {model} has no choices")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise ReaderError(f"{model}'s reply was cut off at {MAX_OUTPUT_TOKENS} tokens")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ReaderError(f"{model} returned an empty reply")
    return content


def _upstream_message(payload: object) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return str(message)[:MAX_UPSTREAM_MESSAGE] if message else ""


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
