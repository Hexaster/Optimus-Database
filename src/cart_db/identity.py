"""Conservative identity comparisons for database ingestion, not observations."""
from __future__ import annotations

import hashlib
import json
import re

from .postprocess import AA
from .manufacturing import PROCESS_FIELDS, compare_process, process_key, similarity_key

ENTITIES = ("binder", "car", "manufacturing")


# Serialize identity values deterministically so dictionary order cannot change a fingerprint.
def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


# Hash the deterministic JSON representation used by candidate indexes.
def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


# Accept only nonempty sequences composed entirely of the 20 standard amino-acid letters.
def certain(value):
    # Only a nonempty string containing exclusively standard amino acids is certain sequence
    # identity evidence.
    return isinstance(value, str) and bool(value) and set(value) <= AA


# Check nested values for reported content; zero and False still count as present.
def present(value):
    # Search object values recursively; a container alone is not evidence of reported content.
    if isinstance(value, dict):
        # Build mapped values from value.values().
        return any(present(v) for v in value.values())
    # Search list elements without treating an empty list as reported content.
    if isinstance(value, list):
        # Build mapped values from value.
        return any(present(v) for v in value)
    # Scalar zero/False are present; null and empty text are not.
    return value is not None and value != ""


def comparison_value(value):
    """Ignore measurement wording for retrieval only; never infer equivalence."""
    # Remove raw wording only from the retrieval key; source records retain it.
    if isinstance(value, dict):
        # Collect items from value.items() only where k != 'raw'.
        return {k: comparison_value(v) for k, v in value.items() if k != "raw"}
    # Preserve list order while projecting nested retrieval values.
    if isinstance(value, list):
        # Build mapped values from value.
        return [comparison_value(v) for v in value]
    return value


# Build a complete sequence/process signature when enough identifying information is reported.
def strong_key(table, data):
    # Manufacturing identity depends on complete process dimensions rather than sequence.
    if table == "manufacturing":
        key = process_key(data)
        # Use ('complete_process', key) when key is supplied; otherwise use None.
        return ("complete_process", key) if key is not None else None
    # A complete unambiguous scFv supplies a binder sequence signature.
    if table == "binder" and certain(data.get("scfv_sequence")):
        return ("scfv", data["scfv_sequence"])
    # CAR signatures describe ordered backbone modules, separately from the binder.
    if table == "car":
        # Use an empty list when data.get('modules') is missing or empty.
        modules = data.get("modules") or []
        # Require a nonempty backbone and a certain sequence for every module.
        if modules and all(certain(m.get("sequence")) for m in modules):
            # Build mapped values from modules.
            return ("backbone", [[m["module_type"], m["sequence"]] for m in modules])
    return None


def features(table, data):
    """Return indexed retrieval keys, including deliberately weak candidates."""
    result = []

    # Index a nonempty feature with both its hash and original comparison value.
    def add(basis, value):
        # Do not index an absent feature as a matchable value.
        if present(value):
            result.append((basis, digest(value), value))

    # Index each reported name/alias so any source label can retrieve a candidate.
    for name in [data.get("name"), *(data.get("aliases") or [])]:
        # Ignore empty or non-text labels when building name lookup keys.
        if isinstance(name, str) and name.strip():
            add("name", name.strip().casefold())
    key = strong_key(table, data)
    # Index complete identity information when available, alongside weaker features.
    if key:
        add(*key)
    # Partial binder chains can retrieve candidates but do not prove whole-binder identity.
    if table == "binder":
        # Keep heavy- and light-chain lookup features distinct.
        for chain in ("heavy_chain", "light_chain"):
            # Use an empty mapping when data.get(chain) is missing or empty.
            item = data.get(chain) or {}
            # Ambiguous residues cannot support exact chain lookup.
            if certain(item.get("sequence")):
                add(chain, item["sequence"])
    # Preserve ordered module types/names as additional CAR retrieval hints.
    if table == "car":
        # Use an empty list when data.get('modules') is missing or empty.
        modules = data.get("modules") or []
        # Build mapped values from modules.
        add("module_types", [m["module_type"] for m in modules])
        add("module_names", module_names(data))
        # Concatenate only complete certain backbones for a broader sequence-retrieval hint.
        if modules and all(certain(m.get("sequence")) for m in modules):
            # Build mapped values from modules.
            add("backbone_sequence", "".join(m["sequence"] for m in modules))
    # Index both process similarity and individual dimensions for later comparison.
    if table == "manufacturing":
        add("process_similarity", similarity_key(data))
        # Retain each main process dimension as its own lookup basis.
        for field in PROCESS_FIELDS:
            add(field, comparison_value(data.get(field)))
    # Build mapped values from result.
    return list({(b, h): (b, h, v) for b, h, v in result}.values())


# Exclude empty and generic binder labels before using exact names as identity evidence.
def identifying_names(data):
    names = set()
    # Consider the primary name and all reported aliases without inventing synonyms.
    for value in [data.get("name"), *(data.get("aliases") or [])]:
        # Skip names that contain no usable text.
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        # Generic placeholders cannot establish a binder identity.
        if value.casefold() in {"unknown", "unnamed", "binder", "scfv", "antibody", "未命名", "未知"}:
            continue
        # An antigen-only label such as anti-CD19 describes specificity, not a unique binder.
        if re.fullmatch(r"(?:anti[- ]?|抗)CD\d+(?:[- ]?(?:scfv|antibody|抗体))?", value, re.I):
            continue
        names.add(value)
    return names


# Return ordered module-type/name pairs only when every module has a reported name.
def module_names(data):
    # Use an empty list when data.get('modules') is missing or empty.
    modules = data.get("modules") or []
    # Module-name identity requires a name for every position, with order preserved.
    if modules and all(isinstance(m.get("source_molecule"), str) and m["source_molecule"].strip() for m in modules):
        # Build mapped values from modules.
        return [[m["module_type"], m["source_molecule"].strip()] for m in modules]
    return None


def compare(table, incoming, existing):
    """Name/sequence identity with explicit red flags; no admission decisions."""
    # Delegate protocol comparisons to the manufacturing-specific rules.
    if table == "manufacturing":
        return compare_process(incoming, existing)
    a, b = strong_key(table, incoming), strong_key(table, existing)
    conflicts, agreements = [], []
    # Binder identity checks sequence conflicts before accepting exact source names.
    if table == "binder":
        name_match = bool(identifying_names(incoming) & identifying_names(existing))
        # Different complete scFv signatures are recorded as conflicting sequence information.
        if a and b and a != b:
            conflicts.append("scfv_sequence")
        # Compare corresponding heavy/light chains without mixing their molecular scopes.
        for chain in ("heavy_chain", "light_chain"):
            # Apply the explicit fallbacks to missing/empty values while retaining any reported
            # nonempty values.
            left, right = incoming.get(chain) or {}, existing.get(chain) or {}
            # Only equal, known scopes make corresponding chain sequences comparable.
            if (left.get("scope") == right.get("scope") and left.get("scope")
                    and certain(left.get("sequence")) and certain(right.get("sequence"))):
                # Use agreements when left sequence equals right sequence; otherwise use conflicts.
                (agreements if left["sequence"] == right["sequence"] else conflicts).append(chain)
        # An identifying name cannot override contradictory known sequence evidence.
        if name_match and conflicts:
            return dict(verdict="conflict", conflicts=conflicts, reason="名称或 alias 相同，但对应的已知序列不同，需人工检查。")
        # Different complete scFvs normally distinguish binders, subject to the chain-only
        # exception.
        if a and b and a != b:
            # Matching VH/VL with different scFvs leaves linker/orientation identity unresolved.
            if set(agreements) == {"heavy_chain", "light_chain"}:
                return dict(verdict="possible", reason="VH/VL 相同但完整 scFv 不同，需要核对连接肽及方向。")
            return dict(verdict="distinct", reason="完整 scFv 序列不同。")
        # Equal scFvs do not erase contradictory chain annotations.
        if a and b and a == b and conflicts:
            return dict(verdict="conflict", conflicts=conflicts, reason="完整 scFv 相同但链序列注释冲突。")
        left, right = incoming.get("linker"), existing.get("linker")
        # Reported linker disagreement requires source review even when names or scFvs match.
        if (name_match or (a and a == b)) and present(left) and present(right) and left != right:
            return dict(verdict="possible", conflicts=["linker"], reason="连接肽描述不同，需要来源审核。")
        # Accept an exact identifying name only after known sequence/linker conflicts have been
        # checked.
        if name_match:
            return dict(verdict="same", basis="exact_name_or_alias", reason="名称或来源确认的 alias 精确匹配，已知序列无冲突。")
    # For CAR backbones, compare ordered module names and sequences while retaining missing
    # information.
    else:
        names_a, names_b = module_names(incoming), module_names(existing)
        # An ordered module-name match requires a complete signature on both sides.
        name_match = names_a is not None and names_a == names_b
        # Compare modules position by position; do not reorder the backbone to manufacture a match.
        for i, (left, right) in enumerate(zip(incoming.get("modules") or [], existing.get("modules") or [])):
            # Modules of different types are not corresponding components for annotation checks.
            if left["module_type"] != right["module_type"]:
                continue
            # A source-molecule name agrees only when the incoming name is nonempty and both trimmed
            # names match.
            same_name = bool(left.get("source_molecule")) and (left.get("source_molecule") or "").strip() == (right.get("source_molecule") or "").strip()
            # The same named component with different known sequences is a red flag.
            if same_name and certain(left.get("sequence")) and certain(right.get("sequence")) and left["sequence"] != right["sequence"]:
                conflicts.append(f"modules[{i}].sequence")
            # Conflicting reported lengths block an otherwise matching backbone identity.
            if (name_match or (a and a == b)) and left.get("length") is not None and right.get("length") is not None and left["length"] != right["length"]:
                conflicts.append(f"modules[{i}].length")
        # Return annotation conflicts before considering positive CAR matches.
        if conflicts:
            return dict(verdict="conflict", conflicts=conflicts, reason="同名对应组件的已知序列或长度冲突，需人工检查。")
        # Ordered component names can establish identity once known conflicts are excluded.
        if name_match:
            return dict(verdict="same", basis="ordered_module_names", reason="有序模块类型和组件名称一致，已知序列无冲突。")
        # Different structured signatures still require checking the full backbone sequence.
        if a and b and a != b:
            # A different concatenated backbone sequence establishes distinct CAR backbones.
            if "".join(m[1] for m in a[1]) != "".join(m[1] for m in b[1]):
                return dict(verdict="distinct", reason="完整骨架序列不同。")
        # Matching complete sequences still require a source-molecule annotation check.
        if a and b and a == b:
            # Inspect every matched module for inconsistent source-molecule descriptions.
            for i, (left, right) in enumerate(zip(incoming["modules"], existing["modules"])):
                # Equal sequences with different reported source molecules remain review candidates.
                if present(left.get("source_molecule")) and present(right.get("source_molecule")) and left["source_molecule"] != right["source_molecule"]:
                    return dict(verdict="possible", conflicts=[f"modules[{i}].source_molecule"], reason="相同序列的来源分子注释不同。")
    # Accept matching complete sequence signatures only after the preceding conflict checks.
    if a and b and a == b:
        return dict(verdict="same", basis="exact_sequence", reason="完整序列一致。")
    return dict(verdict="possible", agreements=agreements, conflicts=conflicts, reason="身份信息不足或描述不同，需要审核是否重复。")
