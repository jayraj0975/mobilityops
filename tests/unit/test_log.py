import json
import logging

from mobilityops.log import JsonFormatter, redact


def _format(**ctx: object) -> dict[str, object]:
    rec = logging.LogRecord("mobilityops.t", logging.INFO, "f", 1, "hello %s", ("world",), None)
    rec.ctx = ctx  # type: ignore[attr-defined]
    return json.loads(JsonFormatter().format(rec))  # type: ignore[no-any-return]


def test_output_is_one_json_object_with_message_and_context() -> None:
    out = _format(rows=5)
    assert out["msg"] == "hello world"
    assert out["level"] == "INFO"
    assert out["rows"] == 5


def test_secret_like_keys_are_redacted_even_when_nested() -> None:
    out = _format(api_key="sk-live", nested={"Authorization": "Bearer abc", "ok": 1})
    assert out["api_key"] == "***redacted***"
    assert out["nested"] == {"Authorization": "***redacted***", "ok": 1}
    assert "sk-live" not in json.dumps(out)


def test_redact_leaves_ordinary_values_alone() -> None:
    assert redact({"zone": 3, "rows": [1, 2]}) == {"zone": 3, "rows": [1, 2]}
