import pytest

from app.execution.assertions import AssertionFailure, evaluate_assertions, extract_values
from app.execution.context import deep_merge, render, render_path_parameters
from app.execution.protocols import _resolve_url


def test_render_preserves_full_template_type_and_interpolates_text() -> None:
    context = {"user": {"id": 42}, "token": "abc"}

    assert render("{{ user.id }}", context) == 42
    assert render("Bearer {{ token }}", context) == "Bearer abc"
    assert render({"ids": ["{{ user.id }}"]}, context) == {"ids": [42]}


def test_deep_merge_keeps_nested_defaults() -> None:
    assert deep_merge(
        {"headers": {"Accept": "json", "X-App": "qa"}},
        {"headers": {"X-App": "test"}},
    ) == {"headers": {"Accept": "json", "X-App": "test"}}


def test_render_path_parameters_uses_context_or_explicit_values() -> None:
    assert render_path_parameters(
        "/users/{user_id}/orders/:order_id",
        {"user_id": "alice@example.com", "order_id": 42},
    ) == "/users/alice%40example.com/orders/42"
    assert render_path_parameters(
        "/users/{user_id}", {"user_id": "context"}, {"user_id": "override"}
    ) == "/users/override"

    with pytest.raises(ValueError, match="Missing path parameter: user_id"):
        render_path_parameters("/users/{user_id}", {})


def test_resolve_url_supports_template_base_url_and_api_path() -> None:
    assert _resolve_url({"base_url": "https://example.test/", "path": "/users"}) == (
        "https://example.test/users"
    )
    assert _resolve_url({"url": "https://override.test/health"}) == (
        "https://override.test/health"
    )


def test_assertions_and_extraction() -> None:
    response = {"status_code": 200, "body": {"data": {"token": "secret"}}}
    evaluate_assertions(
        response,
        [
            {"source": "status_code", "operator": "equals", "expected": 200},
            {"source": "body.data.token", "operator": "contains", "expected": "sec"},
            {"source": "body.data.token", "operator": "exists"},
        ],
    )
    assert extract_values(
        response, [{"name": "access_token", "source": "body.data.token"}]
    ) == {"access_token": "secret"}

    with pytest.raises(AssertionFailure):
        evaluate_assertions(
            response, [{"source": "status_code", "operator": "equals", "expected": 201}]
        )
