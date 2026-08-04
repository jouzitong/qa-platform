import ast
import operator
import re
from collections.abc import Callable
from secrets import choice, randbelow, token_hex
from string import ascii_letters, digits
from typing import Any


class ExpressionError(ValueError):
    pass


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_COMPARE_OPERATORS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_ALLOWED_NAMES = {
    "response", "request", "context", "params", "random", "True", "False", "None"
}


def _contains(container: Any, value: Any) -> bool:
    return value in container


def _exists(container: Any, key: Any | None = None) -> bool:
    if key is None:
        return container is not None
    try:
        if isinstance(container, dict):
            return key in container
        container[key]
        return True
    except (KeyError, IndexError, TypeError):
        return False


def _match(pattern: str, value: Any) -> bool:
    return re.search(pattern, str(value)) is not None


def _integer_argument(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ExpressionError(f"random.{label} requires an integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ExpressionError(f"random.{label} requires an integer") from None
    if result != value:
        raise ExpressionError(f"random.{label} requires an integer")
    return result


def _length(value: Any, label: str, *, maximum: int = 256) -> int:
    result = _integer_argument(value, label)
    if not 1 <= result <= maximum:
        raise ExpressionError(f"random.{label} length must be between 1 and {maximum}")
    return result


def _random_uuid(length: int = 32) -> str:
    size = _length(length, "uuid", maximum=128)
    return token_hex((size + 1) // 2)[:size]


def _random_string(length: int = 16) -> str:
    size = _length(length, "string")
    alphabet = ascii_letters + digits
    return "".join(choice(alphabet) for _ in range(size))


def _random_int(minimum: int = 0, maximum: int | None = None) -> int:
    lower = _integer_argument(minimum, "int")
    upper = lower if maximum is None else _integer_argument(maximum, "int")
    if maximum is None:
        lower = 0
    if lower > upper:
        raise ExpressionError("random.int minimum must be less than or equal to maximum")
    return lower + randbelow(upper - lower + 1)


def _random_float(minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        lower = float(minimum)
        upper = float(maximum)
    except (TypeError, ValueError, OverflowError):
        raise ExpressionError("random.float requires numeric bounds") from None
    if lower > upper:
        raise ExpressionError("random.float minimum must be less than or equal to maximum")
    # Use a cryptographically seeded source without exposing Python's global RNG state.
    fraction = randbelow(2**53) / 2**53
    return lower + (upper - lower) * fraction


_RANDOM_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "uuid": _random_uuid,
    "string": _random_string,
    "int": _random_int,
    "integer": _random_int,
    "float": _random_float,
}
_RANDOM_NAMESPACE = _RANDOM_FUNCTIONS


_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "len": len,
    "contains": _contains,
    "exists": _exists,
    "match": _match,
    "starts_with": lambda value, prefix: str(value).startswith(str(prefix)),
    "ends_with": lambda value, suffix: str(value).endswith(str(suffix)),
    "lower": lambda value: str(value).lower(),
    "upper": lambda value: str(value).upper(),
}


def evaluate_expression(expression: str, variables: dict[str, Any]) -> Any:
    tree = parse_expression(expression)
    scope = {name: variables.get(name, {}) for name in _ALLOWED_NAMES if name in variables}
    scope["random"] = _RANDOM_NAMESPACE
    return _evaluate(tree.body, scope)


def parse_expression(expression: str) -> ast.Expression:
    if not expression.strip():
        raise ExpressionError("Expression cannot be empty")
    if len(expression) > 2000:
        raise ExpressionError("Expression is too long (maximum 2000 characters)")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"Invalid expression syntax: {exc.msg}") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > 250:
        raise ExpressionError("Expression is too complex (maximum 250 AST nodes)")
    _validate(tree)
    return tree


def _validate(tree: ast.AST) -> None:
    allowed = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Attribute,
        ast.Subscript,
        ast.Slice,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.USub,
        ast.UAdd,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Gt,
        ast.GtE,
        ast.Lt,
        ast.LtE,
        ast.In,
        ast.NotIn,
        ast.Is,
        ast.IsNot,
        ast.Call,
        ast.Load,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ExpressionError(f"Unsupported expression element: {type(node).__name__}")
        if isinstance(node, ast.Name):
            if node.id not in _ALLOWED_NAMES and node.id not in _FUNCTIONS:
                raise ExpressionError(f"Unknown name: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExpressionError("Private attributes are not allowed")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_allowed = node.func.id in _FUNCTIONS
            elif isinstance(node.func, ast.Attribute):
                call_allowed = (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "random"
                    and node.func.attr in _RANDOM_FUNCTIONS
                )
            else:
                call_allowed = False
            if not call_allowed:
                raise ExpressionError("Only whitelisted helper functions can be called")
            if node.keywords:
                raise ExpressionError("Keyword arguments are not supported")
        elif isinstance(node, (ast.List, ast.Tuple, ast.Dict)):
            if len(getattr(node, "elts", getattr(node, "keys", []))) > 100:
                raise ExpressionError("Collection literal is too large")


def _evaluate(node: ast.AST, scope: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _FUNCTIONS:
            return _FUNCTIONS[node.id]
        return scope.get(node.id)
    if isinstance(node, ast.Attribute):
        value = _evaluate(node.value, scope)
        if isinstance(value, dict):
            if node.attr not in value:
                raise ExpressionError(f"Attribute not found: {node.attr}")
            return value[node.attr]
        raise ExpressionError(f"Cannot access attribute {node.attr!r} on this value")
    if isinstance(node, ast.Subscript):
        value = _evaluate(node.value, scope)
        key = _evaluate(node.slice, scope)
        try:
            return value[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExpressionError(f"Subscript lookup failed: {key!r}") from exc
    if isinstance(node, ast.Slice):
        return slice(
            _evaluate(node.lower, scope) if node.lower else None,
            _evaluate(node.upper, scope) if node.upper else None,
            _evaluate(node.step, scope) if node.step else None,
        )
    if isinstance(node, ast.List):
        return [_evaluate(item, scope) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_evaluate(item, scope) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _evaluate(key, scope): _evaluate(value, scope)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for item in node.values:
                result = _evaluate(item, scope)
                if not result:
                    return result
            return result
        result = False
        for item in node.values:
            result = _evaluate(item, scope)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, scope)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
        return +value
    if isinstance(node, ast.BinOp):
        operation = _BINARY_OPERATORS[type(node.op)]
        return operation(_evaluate(node.left, scope), _evaluate(node.right, scope))
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, scope)
        for operation_node, comparator_node in zip(
            node.ops, node.comparators, strict=True
        ):
            right = _evaluate(comparator_node, scope)
            if not _COMPARE_OPERATORS[type(operation_node)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        function = _evaluate(node.func, scope)
        return function(*[_evaluate(argument, scope) for argument in node.args])
    raise ExpressionError(f"Unsupported expression element: {type(node).__name__}")
