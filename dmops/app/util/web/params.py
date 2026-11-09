"""请求参数解析。"""

from flask import request

from app.util.errors import ApiError
from app.util.web import response


def query_str(name: str, default: str = '') -> str:
    value = request.args.get(name, default)
    return (value or '').strip()


def query_int(name: str, default: int, minimum: int | None = None,
              maximum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw is None or raw == '':
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise ApiError(
                response.CODE_BAD_REQUEST,
                f'参数 {name} 必须是整数',
                f'invalid int query param {name}={raw!r}',
                400,
            ) from error
    if minimum is not None and value < minimum:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'参数 {name} 不能小于 {minimum}',
            f'query param {name}={value} less than {minimum}',
            400,
        )
    if maximum is not None and value > maximum:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'参数 {name} 不能大于 {maximum}',
            f'query param {name}={value} greater than {maximum}',
            400,
        )
    return value


def json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '请求体必须是 JSON 对象',
            'request body must be a JSON object',
            400,
        )
    return body
