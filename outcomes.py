"""Shared call failure categories. Provider details remain in the discussion log."""
import re


class CallFailure(ValueError):
    def __init__(self, kind, detail):
        super().__init__(detail)
        self.kind = kind


def failure_kind(detail):
    if not detail:
        return None
    for kind, pattern in (
        ("account_access", r"security[ _-]+check|authentication|unauthenticated|未登录|出口不匹配|公网 IP|Claude 的出口|关闭此轮 Claude"),
        ("provider_safety", r"content[ _-]?filter|safety[ _-]?block|blocked[ _-]by[ _-]safety|safety[ _-]policy|responsibleaipolicyviolation|内容安全|未完成本轮[：:]\s*(?:refusal|safety)\b"),
        ("quota", r"rate[ _-]?limit|resource[ _-]?exhausted|usage[ _-]?limit|\bquota\b|quota[ _-]?(?:exceeded|limit|exhausted)|额度(?:耗尽|或频率受限)|\b429\b"),
        ("tool_permission", r"工具.{0,16}(?:拒绝|权限不足|无权限)|权限被拒|permission[ _-]?denied|sandbox[ _-]denied|approval[ _-]denied|已拒绝"),
        ("timeout", r"调用超时|deadline[ _-]exceeded|timed out|\btimeout\b"),
        ("interrupted", r"中断|停止|cancelled|canceled|aborted|connection reset|connection closed|broken pipe"),
    ):
        if re.search(pattern, detail, re.I):
            return kind
    return "provider_error"
