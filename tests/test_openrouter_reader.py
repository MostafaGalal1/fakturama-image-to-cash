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
    assert body["response_format"] == {"type": "json_object"}
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


def test_shrinks_a_large_image_for_upload_and_leaves_the_original_alone(sample_order):
    original = Image.new("RGB", (3000, 1500), "white")
    before = original.tobytes()
    seen: list[httpx.Request] = []
    serve(seen, json=reply_with(sample_order.model_dump_json())).read(original)
    _, uploaded = uploaded_image(seen[0])
    assert uploaded.size == (openrouter.MAX_UPLOAD_LONG_EDGE, openrouter.MAX_UPLOAD_LONG_EDGE // 2)
    assert original.size == (3000, 1500)
    assert original.tobytes() == before


def noise_image() -> Image.Image:
    return Image.effect_noise((160, 160), 100).convert("RGB")


def png_size(image: Image.Image) -> int:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return len(buffer.getvalue())


def test_sends_jpeg_when_the_png_is_too_large(monkeypatch, sample_order):
    image = noise_image()
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


@pytest.mark.parametrize("value", [None, "", "   "])
def test_needs_an_api_key(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(API_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(API_KEY_ENV, value)
    with pytest.raises(ReaderError, match=API_KEY_ENV):
        OpenRouterReader.from_env(MODEL)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "rejected the key"), (402, "no credit"), (429, "rate-limited"), (500, "HTTP 500"), (503, "HTTP 503")],
)
def test_http_errors_say_what_went_wrong_without_the_key(prepared_image, status, expected):
    payload = {"error": {"message": f"upstream said no to {API_KEY}", "code": status}}
    with pytest.raises(ReaderError, match=expected) as caught:
        serve(status=status, json=payload).read(prepared_image)
    message = str(caught.value)
    assert MODEL in message
    assert "upstream said no" in message
    assert API_KEY not in message


def test_http_error_without_a_json_body(prepared_image):
    with pytest.raises(ReaderError, match="HTTP 502"):
        serve(status=502, text="<html>Bad gateway</html>").read(prepared_image)


def test_upstream_messages_are_cut_short(prepared_image):
    payload = {"error": {"message": "x" * 5000}}
    with pytest.raises(ReaderError) as caught:
        serve(status=400, json=payload).read(prepared_image)
    assert len(str(caught.value)) < MAX_MESSAGE_LENGTH


def test_an_error_inside_a_200_reply_is_reported(prepared_image):
    payload = {"error": {"message": "Upstream error from Nvidia: unsupported regex", "code": 502}}
    with pytest.raises(ReaderError, match="Upstream error from Nvidia"):
        serve(json=payload).read(prepared_image)


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": ["text"]}, [], "text"])
def test_a_reply_without_choices_is_rejected(prepared_image, payload):
    with pytest.raises(ReaderError, match="no choices"):
        serve(json=payload).read(prepared_image)


def test_a_reply_that_is_not_json_is_rejected(prepared_image):
    with pytest.raises(ReaderError, match="not JSON"):
        serve(text="<html>maintenance</html>").read(prepared_image)


def test_a_reply_cut_off_at_the_token_limit_is_rejected(sample_order, prepared_image):
    content = sample_order.model_dump_json()[:100]
    with pytest.raises(ReaderError, match="cut off"):
        serve(json=reply_with(content, finish_reason="length")).read(prepared_image)


@pytest.mark.parametrize("content", [None, "", "   ", 42])
def test_an_empty_reply_is_rejected(prepared_image, content):
    with pytest.raises(ReaderError, match="empty reply"):
        serve(json=reply_with(content)).read(prepared_image)


@pytest.mark.parametrize(
    "content", ["Sorry, SECRET-VALUE is unreadable", '{"external_reference": "SECRET-VALUE"}', "[]"]
)
def test_a_reply_that_is_not_a_valid_order_is_rejected_without_echoing_it(prepared_image, content):
    with pytest.raises(ReaderError, match="not a valid order") as caught:
        serve(json=reply_with(content)).read(prepared_image)
    message = str(caught.value)
    assert "SECRET-VALUE" not in message
    assert len(message) < MAX_MESSAGE_LENGTH


@pytest.mark.parametrize("error", [httpx.ConnectError("name resolution failed"), httpx.ReadTimeout("")])
def test_network_failures_become_reader_errors(prepared_image, error):
    with pytest.raises(ReaderError, match="cannot reach OpenRouter"):
        failing(error).read(prepared_image)


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
