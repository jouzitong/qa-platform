import asyncio
import json
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.execution.assertions import AssertionFailure, extract_values
from app.execution.context import deep_merge, render, render_path_parameters
from app.execution.events import run_events
from app.execution.protocols import ExecutionResult, execute_http, execute_ws
from app.execution.response import attach_payload
from app.execution.validation import validate_api_response
from app.models import ApiDefinition, ApiTemplate, Project, StepRun, TestFlow, TestRun, utcnow


def build_request_config(
    api: ApiDefinition,
    context: dict[str, Any],
    request_override: dict[str, Any] | None = None,
    template: ApiTemplate | None = None,
) -> dict[str, Any]:
    parameters = _effective_parameters(api, template)
    parameter_context = _context_with_parameter_defaults(parameters, context)
    config = deep_merge(template.request if template else {}, api.request)
    config = render(config, parameter_context)
    config = _apply_parameter_values(config, parameters, parameter_context, overwrite=True)
    config = deep_merge(config, request_override or {})
    if not config.get("url") and not config.get("base_url") and config.get("path"):
        config["base_url"] = "{{ base_url }}"
    rendered = render(config, parameter_context)
    rendered = _apply_parameter_values(rendered, parameters, parameter_context, overwrite=False)
    path_params = rendered.get("path_params", {})
    if not isinstance(path_params, dict):
        raise ValueError("request.path_params must be an object")
    for field in ("url", "path"):
        if field in rendered:
            rendered[field] = render_path_parameters(
                str(rendered[field]), context, path_params
            )
    return rendered


def _effective_parameters(
    api: ApiDefinition, template: ApiTemplate | None
) -> list[dict[str, Any]]:
    """Combine template and API parameter definitions, with API values taking precedence."""
    parameters: dict[tuple[str, str], dict[str, Any]] = {}
    for item in [*(template.parameters if template else []), *api.parameters]:
        if not isinstance(item, dict):
            continue
        location = str(item.get("in", "query"))
        name = str(item.get("name", "")).strip()
        if name:
            parameters[(location, name)] = item
    return list(parameters.values())


def _parameter_children(parameter: dict[str, Any]) -> list[dict[str, Any]]:
    children = parameter.get("children")
    if not isinstance(children, list):
        children = parameter.get("child_params")
    if not isinstance(children, list):
        return []
    return [item for item in children if isinstance(item, dict)]


def _parameter_nodes(
    parameters: list[dict[str, Any]],
    parent_path: tuple[str, ...] = (),
    inherited_location: str = "query",
) -> list[tuple[str, tuple[str, ...], dict[str, Any]]]:
    nodes: list[tuple[str, tuple[str, ...], dict[str, Any]]] = []
    for parameter in parameters:
        name = str(parameter.get("name", "")).strip()
        if not name:
            continue
        location = inherited_location if parent_path else str(parameter.get("in", "query"))
        path = (*parent_path, name)
        nodes.append((location, path, parameter))
        if str(parameter.get("type", "string")) == "object":
            nodes.extend(_parameter_nodes(_parameter_children(parameter), path, location))
    return nodes


def _lookup_parameter_value(
    context: dict[str, Any], path: tuple[str, ...]
) -> tuple[Any, bool]:
    dotted = ".".join(path)
    if dotted in context:
        return context[dotted], True
    current: Any = context
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None, False
        current = current[part]
    return current, True


def _has_nested_value(target: dict[str, Any], path: tuple[str, ...]) -> bool:
    _, found = _lookup_parameter_value(target, path)
    return found


def _set_nested_value(
    target: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
    *,
    overwrite: bool,
) -> None:
    if not path:
        return
    current = target
    for part in path[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    if overwrite or path[-1] not in current:
        current[path[-1]] = value


def _expand_dotted_context(context: dict[str, Any]) -> None:
    for key, value in list(context.items()):
        if isinstance(key, str) and "." in key:
            _set_nested_value(
                context,
                tuple(part for part in key.split(".") if part),
                value,
                overwrite=False,
            )


def _context_with_parameter_defaults(
    parameters: list[dict[str, Any]], context: dict[str, Any]
) -> dict[str, Any]:
    enriched = deep_merge({}, context)
    _expand_dotted_context(enriched)
    for _location, path, parameter in _parameter_nodes(parameters):
        if _lookup_parameter_value(enriched, path)[1] or "default" not in parameter:
            continue
        default = render(parameter["default"], enriched)
        _set_nested_value(
            enriched,
            path,
            _coerce_parameter_value(default, parameter),
            overwrite=False,
        )
    return enriched


def _apply_parameter_values(
    config: dict[str, Any],
    parameters: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    overwrite: bool,
) -> dict[str, Any]:
    result = dict(config)
    for location, path, parameter in _parameter_nodes(parameters):
        value, found = _lookup_parameter_value(context, path)
        if not found:
            continue
        value = _coerce_parameter_value(value, parameter)
        if location == "path":
            path_params = result.get("path_params")
            if not isinstance(path_params, dict):
                path_params = {}
            path_name = path[-1]
            if overwrite or path_name not in path_params:
                path_params[path_name] = value
            result["path_params"] = path_params
            continue
        if location not in {"query", "header", "body"}:
            continue
        if location == "body":
            values = result.get("body")
            if not isinstance(values, dict):
                values = {}
            if overwrite or not _has_nested_value(values, path):
                _set_nested_value(values, path, value, overwrite=overwrite)
            result["body"] = values
            continue
        config_field = "headers" if location == "header" else location
        values = result.get(config_field)
        if not isinstance(values, dict):
            values = {}
        if overwrite or not _has_nested_value(values, path):
            _set_nested_value(values, path, value, overwrite=overwrite)
        result[config_field] = values
    return result


def _coerce_parameter_value(value: Any, parameter: dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    parameter_type = str(parameter.get("type", "string"))
    if parameter_type == "integer":
        try:
            return int(value)
        except ValueError:
            return value
    if parameter_type == "number":
        try:
            return float(value)
        except ValueError:
            return value
    if parameter_type == "boolean" and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if parameter_type in {"object", "array"}:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


async def execute_api_once(
    api: ApiDefinition,
    context: dict[str, Any],
    request_override: dict[str, Any] | None = None,
    template: ApiTemplate | None = None,
) -> ExecutionResult:
    config = build_request_config(api, context, request_override, template)
    if api.protocol == "http":
        result = await execute_http(config)
        result.response = attach_payload(result.response, api.response_unpack)
        return result
    if api.protocol == "ws":
        result = await execute_ws(config)
        result.response = attach_payload(result.response, api.response_unpack)
        return result
    raise ValueError(f"Unsupported protocol: {api.protocol}")


async def execute_flow(session: Session, run_id: str) -> None:
    run = session.get(TestRun, run_id)
    if not run:
        return
    flow = session.get(TestFlow, run.flow_id)
    if not flow:
        run.status = "failed"
        run.error = "Flow not found"
        session.commit()
        return
    project = session.get(Project, flow.project_id)

    run.status = "running"
    run.started_at = utcnow()
    context = deep_merge(project.variables if project else {}, flow.variables)
    context = deep_merge(context, run.inputs)
    # Keep the mutable working context separate so SQLAlchemy can detect JSON changes.
    run.context = dict(context)
    session.commit()
    await run_events.publish(run.id, {"type": "run_started", "run_id": run.id})

    try:
        for position, step in enumerate(flow.steps):
            if not step.get("enabled", True):
                continue
            await _execute_step(session, run, step, position, context)
            run.context = dict(context)
            session.commit()
        run.status = "passed"
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
    finally:
        run.context = dict(context)
        run.finished_at = utcnow()
        session.commit()
        await run_events.publish(
            run.id,
            {"type": "run_finished", "run_id": run.id, "status": run.status, "error": run.error},
        )


async def _execute_step(
    session: Session,
    run: TestRun,
    step: dict[str, Any],
    position: int,
    context: dict[str, Any],
) -> None:
    api = session.get(ApiDefinition, step["api_id"])
    if not api or api.project_id != session.get(TestFlow, run.flow_id).project_id:
        raise ValueError(f"API not found in this project: {step['api_id']}")
    template = session.get(ApiTemplate, api.template_id) if api.template_id else None

    retry = step.get("retry", {})
    max_attempts = max(1, int(retry.get("max_attempts", 1)))
    interval_ms = max(0, int(retry.get("interval_ms", 0)))
    backoff = max(1.0, float(retry.get("backoff_multiplier", 1)))
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        started = perf_counter()
        result: ExecutionResult | None = None
        extracted: dict[str, Any] = {}
        assertion_results: list[dict[str, Any]] = []
        status = "passed"
        error: str | None = None
        try:
            result = await execute_api_once(
                api, context, step.get("request", {}), template=template
            )
            request_config = build_request_config(
                api, context, step.get("request", {}), template
            )
            validation = validate_api_response(
                session,
                api,
                request=request_config,
                response=result.response,
                context=context,
                step_assertions=step.get("assertions", []),
                step_disabled_assertion_ids=step.get("disabled_assertion_ids", []),
            )
            assertion_results = validation["results"]
            if not validation["passed"]:
                failures = [
                    item["message"]
                    for item in assertion_results
                    if not item["passed"]
                ]
                raise AssertionFailure("; ".join(failures))
            extracted = extract_values(result.response, step.get("extractors", []))
            context.update(extracted)
        except Exception as exc:
            status = "failed"
            error = str(exc)
            last_error = exc

        duration_ms = (perf_counter() - started) * 1000
        record = StepRun(
            run_id=run.id,
            step_id=step["id"],
            step_name=step["name"],
            position=position,
            attempt=attempt,
            status=status,
            duration_ms=duration_ms,
            request_snapshot=result.request if result else {},
            response_snapshot=result.response if result else None,
            extracted=extracted,
            assertion_results=assertion_results,
            error=error,
        )
        session.add(record)
        session.commit()
        await run_events.publish(
            run.id,
            {
                "type": "step_finished",
                "run_id": run.id,
                "step_id": step["id"],
                "attempt": attempt,
                "status": status,
                "error": error,
            },
        )
        if status == "passed":
            return
        if attempt < max_attempts and interval_ms:
            await asyncio.sleep((interval_ms / 1000) * (backoff ** (attempt - 1)))

    assert last_error is not None
    raise last_error
