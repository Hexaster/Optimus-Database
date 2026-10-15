"""Chinese operator messages; machine field names and original source text stay intact."""
import argparse
import json


TABLE_NAMES = {"binder": "结合域", "car": "CAR 构型", "manufacturing": "制造工艺",
               "abc_combination_db1": "组合", "evidence": "证据"}
STATUS_NAMES = {"published": "已入库", "pending": "待审核", "invalid": "质检未通过"}
PENDING_REASONS = {
    "Reviewed target is still pending": "审核指定的目标尚未入库",
    "Dependent entity or combination is pending": "依赖的实体或组合尚未入库",
    "Reviewed new entity now has an exact accepted match; review again": "已有实体与审核决定冲突，需要重新审核",
    "Ambiguous candidates or normalization review flags": "存在不确定的候选匹配或规范化问题",
    "Incomplete identity parameters; source review required": "身份参数不完整，需要核对来源",
    "Resolved evidence references disagree with its ABC combination": "证据引用与组合中的实体不一致",
}


class ChineseArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._positionals.title = "位置参数"
        self._optionals.title = "选项"
        for action in self._actions:
            if action.dest == "help":
                action.help = "显示帮助并退出"

    def format_help(self):
        return super().format_help().replace("usage: ", "用法：", 1)

    def format_usage(self):
        return super().format_usage().replace("usage: ", "用法：", 1)

    def error(self, message):
        self.print_usage()
        if not any("\u4e00" <= char <= "\u9fff" for char in message):
            message = "参数缺失或取值不正确，请使用 --help 查看说明。"
        self.exit(2, f"参数错误：{message}\n")


def count_text(counts):
    return "，".join(f"{label} {counts.get(status, 0)} 条" for status, label in STATUS_NAMES.items())


def report_text(report):
    lines = [f"入库批次：{report['batch_id']}", count_text(report["counts"])]
    if report.get("actions") is not None:
        actions = report["actions"]
        lines.append(f"本次新增实体 {actions.get('new_entities', 0)} 条，"
                     f"关联已有实体 {actions.get('linked_entities', 0)} 条，"
                     f"新增组合或证据 {actions.get('new_records', 0)} 条，"
                     f"复用组合或证据 {actions.get('linked_records', 0)} 条")
    identity = report.get("identity_counts", {})
    if identity:
        lines.append(f"已入库实体：匹配结果待确认 {identity.get('unresolved', 0)} 条，类似工艺 {identity.get('similar', 0)} 条，"
                     f"匹配信息冲突 {identity.get('conflict', 0)} 条（不阻塞证据入库）")
    for row in report["records"]:
        if row.get("identity_status") == "conflict":
            details = row.get("identity_details") or {}
            fields = sorted({f for c in details.get("candidates", []) for f in c["comparison"].get("conflicts", [])})
            lines.append(f"匹配信息冲突：第 {row['line_number']} 行 · {TABLE_NAMES[row['table_name']]} · "
                         f"冲突字段 {', '.join(fields) or '来源身份信息'}；暂存编号 {row['stage_id']}")
        if row["status"] == "published":
            continue
        reason = report.get("pending_reasons", {}).get(str(row["stage_id"]))
        explanation = PENDING_REASONS.get(reason, "请查看质检记录或候选实体与来源资料")
        lines.append(f"第 {row['line_number']} 行 · {TABLE_NAMES.get(row['table_name'], '未知记录类型')} · "
                     f"{STATUS_NAMES[row['status']]}：{explanation}；暂存编号 {row['stage_id']}")
    return "\n".join(lines)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, default=str, indent=2)
