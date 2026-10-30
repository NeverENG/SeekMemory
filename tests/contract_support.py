"""从唯一的 OpenAPI 契约校验请求和真实响应，供独立与宿主测试共用。"""

from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
SAMPLES: list[dict] = []


def validate_contract(action: str, data: object, status: int = 200, *, request=False):
    """校验操作的请求体或响应正文，并收集跨语言验证样本。

    Args:
        action: OpenAPI operationId。
        data: 实现返回的 JSON 数据或发送的请求体。
        status: 实际 HTTP 状态码；请求校验时忽略。
        request: 是否校验请求体。

    Raises:
        KeyError: 操作或响应状态未在契约中声明。
        jsonschema.ValidationError: 数据与契约不符。
    """
    path = SPEC["paths"][f"/manage/{action}"]
    operation = next(iter(path.values()))
    body = operation["requestBody"] if request else operation["responses"][str(status)]
    schema = body["content"]["application/json"]["schema"]
    Draft202012Validator(
        {**schema, "components": SPEC["components"]}, format_checker=FormatChecker()
    ).validate(data)
    if not request:
        SAMPLES.append({"action": action, "status": status, "body": data})
