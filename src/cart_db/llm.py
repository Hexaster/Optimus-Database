"""Claude 调用封装：结构化抽取 + 提示词缓存 + 用量计费打点。

方案《六、成本预算》按 Claude Sonnet 5 测算，因此默认 model=claude-sonnet-5。
每次调用都写一条 core.llm_usage，跟踪表「8.预算与用量追踪」的 token 与费用
两列直接取自 core.llm_usage_daily 视图。

注意（Sonnet 5 的接口约束）：
  - 自适应思考默认开启，不要传 budget_tokens（会 400）
  - 不接受 temperature / top_p / top_k（会 400），行为靠提示词控制
  - 深度用 output_config.effort 调，取值 low/medium/high/xhigh/max
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Type

from pydantic import BaseModel

from .config import cost_cny, settings
from .db import connect


class LLMNotConfigured(RuntimeError):
    """未配置 ANTHROPIC_API_KEY —— 本地建库阶段属正常状态。"""


class DailyCapExceeded(RuntimeError):
    """当日 LLM 费用超过 CART_LLM_DAILY_CAP_CNY，防止批量跑飞。"""


def _client():
    if not settings.llm_ready:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY 未配置。本地建库不需要它；"
            "到 Day7 提示词工程时再填进 .env 即可。"
        )
    import anthropic
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def spent_today() -> float:
    with connect() as conn:
        cur = conn.execute(
            "SELECT COALESCE(sum(cost_cny),0) FROM core.llm_usage "
            "WHERE called_at::date = current_date"
        )
        return float(cur.fetchone()[0])


def _record_usage(usage, *, model: str, purpose: str,
                  batch_id: uuid.UUID | None, request_id: str | None) -> float:
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cny = cost_cny(usage.input_tokens, usage.output_tokens, cache_read, cache_write)
    with connect() as conn:
        conn.execute(
            """INSERT INTO core.llm_usage
                 (batch_id, model, purpose, input_tokens, output_tokens,
                  cache_read_tokens, cache_write_tokens, cost_cny, request_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (batch_id, model, purpose, usage.input_tokens, usage.output_tokens,
             cache_read, cache_write, cny, request_id),
        )
    return cny


def _strict(schema: dict) -> dict:
    """结构化输出要求每个 object 都带 additionalProperties: false。"""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        schema.setdefault("required", list(schema.get("properties", {})))
    for key in ("properties", "$defs", "definitions"):
        for sub in schema.get(key, {}).values():
            if isinstance(sub, dict):
                _strict(sub)
    if isinstance(schema.get("items"), dict):
        _strict(schema["items"])
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            if isinstance(sub, dict):
                _strict(sub)
    return schema


def extract(
    *,
    schema: Type[BaseModel],
    document: str,
    system_prompt: str,
    purpose: str,
    batch_id: uuid.UUID | None = None,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int = 16000,
) -> BaseModel:
    """从一份文献/专利全文中抽取结构化信息。

    system_prompt 放抽取规则与字段定义（长且稳定），并打上 cache_control ——
    3,600 份文档共用同一段提示词，缓存命中后这部分按输入价的 0.1× 计费。
    document 放在 user 轮，每次都变，不参与缓存。
    """
    model = model or settings.llm_model
    if (spent := spent_today()) >= settings.llm_daily_cap_cny:
        raise DailyCapExceeded(
            f"当日已消耗 ¥{spent:.2f}，达到上限 ¥{settings.llm_daily_cap_cny:.2f}"
        )

    client = _client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},   # 稳定前缀，跨文档复用
        }],
        messages=[{"role": "user", "content": document}],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": _strict(schema.model_json_schema()),
            },
            "effort": effort or settings.llm_effort,
        },
    )
    _record_usage(response.usage, model=model, purpose=purpose,
                  batch_id=batch_id, request_id=getattr(response, "_request_id", None))

    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"输出被 max_tokens 截断，请调大 max_tokens（当前 {max_tokens}）")
    text = next(b.text for b in response.content if b.type == "text")
    return schema.model_validate(json.loads(text))


def count_tokens(*, document: str, system_prompt: str, model: str | None = None) -> int:
    """跑批前先估算输入规模，用于核对预算（方案估 ~180M 输入 token）。"""
    client = _client()
    resp = client.messages.count_tokens(
        model=model or settings.llm_model,
        system=[{"type": "text", "text": system_prompt}],
        messages=[{"role": "user", "content": document}],
    )
    return resp.input_tokens


# ---------------------------------------------------------------------------
# 批量抽取：Batches API 按标准价的 50% 计费。
# Day10-11 要处理 400 篇文献 + 200 件专利，不赶时间的批次走这里，token 费用减半。
# ---------------------------------------------------------------------------
def submit_batch(
    *,
    schema: Type[BaseModel],
    documents: dict[str, str],       # {custom_id: 全文}
    system_prompt: str,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int = 16000,
) -> str:
    """提交批量抽取任务，返回 batch_id（Anthropic 侧的，不是 core.batch_run 的）。"""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = _client()
    json_schema = _strict(schema.model_json_schema())
    system = [{"type": "text", "text": system_prompt,
               "cache_control": {"type": "ephemeral"}}]
    requests = [
        Request(
            custom_id=cid,
            params=MessageCreateParamsNonStreaming(
                model=model or settings.llm_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": doc}],
                output_config={"format": {"type": "json_schema", "schema": json_schema},
                               "effort": effort or settings.llm_effort},
            ),
        )
        for cid, doc in documents.items()
    ]
    return client.messages.batches.create(requests=requests).id


def fetch_batch(anthropic_batch_id: str, schema: Type[BaseModel], *,
                purpose: str, batch_id: uuid.UUID | None = None) -> dict[str, Any]:
    """取回批量结果。结果顺序不保证，按 custom_id 取用，不要按位置取。"""
    client = _client()
    batch = client.messages.batches.retrieve(anthropic_batch_id)
    if batch.processing_status != "ended":
        raise RuntimeError(f"批次尚未完成：{batch.processing_status}")

    out: dict[str, Any] = {}
    for result in client.messages.batches.results(anthropic_batch_id):
        if result.result.type != "succeeded":
            out[result.custom_id] = {"error": result.result.type}
            continue
        msg = result.result.message
        _record_usage(msg.usage, model=msg.model, purpose=purpose,
                      batch_id=batch_id, request_id=None)
        text = next(b.text for b in msg.content if b.type == "text")
        out[result.custom_id] = schema.model_validate(json.loads(text))
    return out
