import base64
import io
import json

import httpx
import pytest
from PIL import Image

from image_to_cash.readers import ReaderError, build_reader
from image_to_cash.readers import openrouter
from image_to_cash.readers.openrouter import API_KEY_ENV, API_URL, DEFAULT_MODEL, OpenRouterReader, describe_field

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


def test_reads_one_field_from_a_crop(prepared_image):
    seen = []
    reader = serve(seen, json=reply_with('{"value": "CHR-ERG-01"}'))
    assert reader.read_field(prepared_image, "items[0].sku") == "CHR-ERG-01"
    body = json.loads(seen[0].content)
    assert body["messages"][0]["content"].startswith("You read one field")
    assert body["messages"][1]["content"][0]["text"] == "Field: item line 1: sku."


@pytest.mark.parametrize("content", ['{"value": null}', '{"value": ""}', "no json", '["CHR-ERG-01"]'])
def test_a_field_the_crop_does_not_show_is_a_reader_error(prepared_image, content):
    with pytest.raises(ReaderError):
        serve(json=reply_with(content)).read_field(prepared_image, "items[0].sku")


def test_field_paths_read_as_words():
    assert describe_field("items[1].unit_net_price") == "item line 2: unit net price"
    assert describe_field("delivery_address.zip") == "delivery address: zip"
