"""Conservative identity comparisons for database ingestion, not observations."""
from __future__ import annotations

import hashlib
import json
import re

from .postprocess import AA
from .manufacturing import PROCESS_FIELDS, compare_process, process_key, similarity_key

ENTITIES = ("binder", "car", "manufacturing")


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def certain(value):
    return isinstance(value, str) and bool(value) and set(value) <= AA


def present(value):
    if isinstance(value, dict):
        return any(present(v) for v in value.values())
    if isinstance(value, list):
        return any(present(v) for v in value)
    return value is not None and value != ""


def comparison_value(value):
    """Ignore measurement wording for retrieval only; never infer equivalence."""
    if isinstance(value, dict):
        return {k: comparison_value(v) for k, v in value.items() if k != "raw"}
    if isinstance(value, list):
        return [comparison_value(v) for v in value]
    return value


def strong_key(table, data):
    if table == "manufacturing":
        key = process_key(data)
        return ("complete_process", key) if key is not None else None
    if table == "binder" and certain(data.get("scfv_sequence")):
        return ("scfv", data["scfv_sequence"])
    if table == "car":
        modules = data.get("modules") or []
        if modules and all(certain(m.get("sequence")) for m in modules):
            return ("backbone", [[m["module_type"], m["sequence"]] for m in modules])
    return None


def features(table, data):
    """Return indexed retrieval keys, including deliberately weak candidates."""
    result = []

    def add(basis, value):
        if present(value):
            result.append((basis, digest(value), value))

    for name in [data.get("name"), *(data.get("aliases") or [])]:
        if isinstance(name, str) and name.strip():
            add("name", name.strip().casefold())
    key = strong_key(table, data)
    if key:
        add(*key)
    if table == "binder":
        for chain in ("heavy_chain", "light_chain"):
            item = data.get(chain) or {}
            if certain(item.get("sequence")):
                add(chain, item["sequence"])
    if table == "car":
        modules = data.get("modules") or []
        add("module_types", [m["module_type"] for m in modules])
        add("module_names", module_names(data))
        if modules and all(certain(m.get("sequence")) for m in modules):
            add("backbone_sequence", "".join(m["sequence"] for m in modules))
    if table == "manufacturing":
        add("process_similarity", similarity_key(data))
        for field in PROCESS_FIELDS:
            add(field, comparison_value(data.get(field)))
    return list({(b, h): (b, h, v) for b, h, v in result}.values())


def identifying_names(data):
    names = set()
    for value in [data.get("name"), *(data.get("aliases") or [])]:
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if value.casefold() in {"unknown", "unnamed", "binder", "scfv", "antibody", "未命名", "未知"}:
            continue
        if re.fullmatch(r"(?:anti[- ]?|抗)CD\d+(?:[- ]?(?:scfv|antibody|抗体))?", value, re.I):
            continue
        names.add(value)
    return names


def module_names(data):
    modules = data.get("modules") or []
    if modules and all(isinstance(m.get("source_molecule"), str) and m["source_molecule"].strip() for m in modules):
        return [[m["module_type"], m["source_molecule"].strip()] for m in modules]
    return None


def compare(table, incoming, existing):
    """Name/sequence identity with explicit red flags; no admission decisions."""
    if table == "manufacturing":
        return compare_process(incoming, existing)
    a, b = strong_key(table, incoming), strong_key(table, existing)
    conflicts, agreements = [], []
    if table == "binder":
        name_match = bool(identifying_names(incoming) & identifying_names(existing))
        if a and b and a != b:
            conflicts.append("scfv_sequence")
        for chain in ("heavy_chain", "light_chain"):
            left, right = incoming.get(chain) or {}, existing.get(chain) or {}
            if (left.get("scope") == right.get("scope") and left.get("scope")
                    and certain(left.get("sequence")) and certain(right.get("sequence"))):
                (agreements if left["sequence"] == right["sequence"] else conflicts).append(chain)
        if name_match and conflicts:
            return dict(verdict="conflict", conflicts=conflicts, reason="名称或 alias 相同，但对应的已知序列不同，需人工检查。")
        if a and b and a != b:
            if set(agreements) == {"heavy_chain", "light_chain"}:
                return dict(verdict="possible", reason="VH/VL 相同但完整 scFv 不同，需要核对连接肽及方向。")
            return dict(verdict="distinct", reason="完整 scFv 序列不同。")
        if a and b and a == b and conflicts:
            return dict(verdict="conflict", conflicts=conflicts, reason="完整 scFv 相同但链序列注释冲突。")
        left, right = incoming.get("linker"), existing.get("linker")
        if (name_match or (a and a == b)) and present(left) and present(right) and left != right:
            return dict(verdict="possible", conflicts=["linker"], reason="连接肽描述不同，需要来源审核。")
        if name_match:
            return dict(verdict="same", basis="exact_name_or_alias", reason="名称或来源确认的 alias 精确匹配，已知序列无冲突。")
    else:
        names_a, names_b = module_names(incoming), module_names(existing)
        name_match = names_a is not None and names_a == names_b
        for i, (left, right) in enumerate(zip(incoming.get("modules") or [], existing.get("modules") or [])):
            if left["module_type"] != right["module_type"]:
                continue
            same_name = bool(left.get("source_molecule")) and (left.get("source_molecule") or "").strip() == (right.get("source_molecule") or "").strip()
            if same_name and certain(left.get("sequence")) and certain(right.get("sequence")) and left["sequence"] != right["sequence"]:
                conflicts.append(f"modules[{i}].sequence")
            if (name_match or (a and a == b)) and left.get("length") is not None and right.get("length") is not None and left["length"] != right["length"]:
                conflicts.append(f"modules[{i}].length")
        if conflicts:
            return dict(verdict="conflict", conflicts=conflicts, reason="同名对应组件的已知序列或长度冲突，需人工检查。")
        if name_match:
            return dict(verdict="same", basis="ordered_module_names", reason="有序模块类型和组件名称一致，已知序列无冲突。")
        if a and b and a != b:
            if "".join(m[1] for m in a[1]) != "".join(m[1] for m in b[1]):
                return dict(verdict="distinct", reason="完整骨架序列不同。")
        if a and b and a == b:
            for i, (left, right) in enumerate(zip(incoming["modules"], existing["modules"])):
                if present(left.get("source_molecule")) and present(right.get("source_molecule")) and left["source_molecule"] != right["source_molecule"]:
                    return dict(verdict="possible", conflicts=[f"modules[{i}].source_molecule"], reason="相同序列的来源分子注释不同。")
    if a and b and a == b:
        return dict(verdict="same", basis="exact_sequence", reason="完整序列一致。")
    return dict(verdict="possible", agreements=agreements, conflicts=conflicts, reason="身份信息不足或描述不同，需要审核是否重复。")
