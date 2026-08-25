"""DOTAD 2.0 → binder.binder 的 parser 骨架。

════════════════════════════════════════════════════════════════════════
【mapping 时效性核实结论（2026-08-24 实测）】

任务交办时的假设是：docs/Mapping/dotad_to_binder.yaml 仍是照 DOTAD 1.0 的
五档结构写的，与磁盘上的 2.0 对不上栏名。**实测结果是相反的** ——

  · docs/Mapping/dotad_to_binder.yaml 档头写明「本档为重写，非增量修改
    （2026-08-20）」，mapping_id 已是 dotad2_to_binder，Part 0 直接指向
    data/raw/dotad/20260824/v2.0/ 下的四个工作簿。其 Part 1 声明的
    metadata 16 栏 / sequences 8 栏与磁盘档案**逐栏完全一致**（见下方
    _METADATA_COLUMNS / _SEQUENCES_COLUMNS，本档已按实测钉死）。
  · 过时的是 docs/SourceRegistry/dotad.yaml 的 notes ——「=> dotad_to_binder.yaml
    需按 2.0 重写……此为待办」这句话在 mapping 于 2026-08-20 重写后就失效了，
    registry 没跟着更新。

所以本 parser 按 mapping 现有的 Part 3 三块 target 写，不改 mapping。
但仍在 iter_source_rows() 里做显式栏名校验（_check_columns），理由：
mapping 与磁盘档案现在对得上，不代表下一版 DOTAD 发布后还对得上；
校验让骨架在「栏名漂移」这个正确的位置立刻失败，而不是静默产出错数据。

════════════════════════════════════════════════════════════════════════
【mapping 与 2.0 档案仍然对不上的地方（实测，逐条）】
本档不修 mapping，只在代码里把这些点变成显式的 reject / ParseError：

 M1 base.Mapping.source_dataset 读的是单数键 `source_dataset`，
    dotad_to_binder.yaml 写的是复数 `source_datasets`（四个工作簿）。
    调那个 property 必抛 ParseError，故本档直接读 mapping.raw["source_datasets"]。
 M2 Part 3 (2) aggregation 声明源栏 acsins_dLmax_ph7.4 / acsins_dLmax_ph6.0，
    但三个 tidy 分页的写法各不相同：
      tidy format    : acsins_dLmax_ph7.4 / acsins_dLmax_ph6.0   ← 与 mapping 一致
      tidy format(2) : acsins_dLmax_pH7.4 / acsins_dLmax_pH6.0   ← 大写 H
      tidy format（3）: acsins_dLmax_ph7.4 / acsins_dLmax_ph6     ← 少 ".0"
    本档只做**精确栏名匹配**，不做大小写/近名归并（那是猜），对不上的走 reject。
 M3 Part 3 (2) experiment_conditions 声明源含 production_batch 与 run，
    这两栏只存在于 tidy format 第一个分页；(2)(3) 两个分页没有。
 M4 Part 3 (3) kd_nm 声明源 'Jain et al.(2024) 的 Octet KD (M)' —— 该分页
    **没有**叫 "Octet KD (M)" 的栏。实际只有两栏带 (M)：
      'Octet b-Hen Lysozyme Kd Monovalent (M)'
      'Octet IgG KD b-Mouse Lysozyme-Fc Avid (M)'
    这两栏测的是对**溶菌酶**的结合（多反应性/非特异对照），不是抗体对自身靶点
    的亲和力。灌进 kd_nm 会污染亲和力字段。本档不映射，走 reject 并把两个
    候选栏名写进 reject 记录，交人决定。
 M5 Part 3 (3) / registry 都写 Adams et al. 分页「10,970 列」，实测 2,807 行 × 17 栏。
 M6 mapping Part 0 写 [Assay Endpoint Dictionary]「35 列」，实测 34 行。
 M7 literature 的 'shanehsazzadeh et al.' 分页没有 antibody_id 栏（首栏是
    Candidate），而 mapping 的 literature.record_key 是 [antibody_id]。整页无法接。

════════════════════════════════════════════════════════════════════════
【本档刻意不做的事】
 · 不实现 assign_uid() / should_include()。base 里它们抛 Undecided("Q2")/("Q4")，
   是有意留的缺口，业务侧未定，继承下来不覆写。跑 run() 到那里停是预期行为。
 · 不跨分页合并同名/近名指标。literature 30 个分页里 HIC / HIC.16 / HIC.pred.15 /
   hic_rt 测法与单位都不同，合并只走 [Assay Endpoint Dictionary] 的
   Harmonized_Endpoint；该表覆盖不到的走 reject，不靠栏名相似度猜。
 · 不 collapse 多次观测。一个抗体在 experimental 与多个 literature 分页里各有
   Tm，全部产出（record_per_source: many 的含义），挑哪个是后续的事。
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from parsers.base import (
    ROOT,
    Interim,
    NullReason,
    ParseError,
    Record,
    SourceParser,
    TargetBlock,
)

# --------------------------------------------------------------------------
# 实测栏名（2026-08-24，data/raw/dotad/20260824/v2.0/）
# --------------------------------------------------------------------------
# 与 mapping Part 1 source_field_inventory 声明的完全一致。写成常量是为了让
# _check_columns 能同时对「mapping 说有什么」和「上次实测是什么」两侧比对。
_METADATA_COLUMNS = [
    "antibody_id", "antibody_name", "Format", "hc_subtype", "lc_subtype",
    "Highest_Clin_Trial", "est_status_asof_feb2025", "Target", "Species",
    "Clinical indication", "PDB", "PDB_reference", "ADAs_rate", "ADAs_reference",
    "production_host", "tag",
]
_SEQUENCES_COLUMNS = [
    "antibody_id", "antibody_name", "VH", "VL",
    "hc_protein_sequence", "lc_protein_sequence", "hc_dna_sequence", "lc_dna_sequence",
]

# 实测填充率 0.0% —— 栏在、值全空。mapping Part 1 已标【实测告警】。
# 不能因为栏名存在就当有值，也不为它们写映射分支。
_EMPTY_METADATA_COLUMNS = ("production_host", "tag")

# literature / experimental 里属于「标识与序列」而非「指标」的栏，
# 逐栏分类时先排除，剩下的才当指标看。
_NON_METRIC_COLUMNS = {
    "antibody_id", "antibody_id.1", "antibody_name", "vh", "vl",
    "hc_subtype", "lc_subtype", "tag", "production_host",
    "production_batch", "run", "technical_replicate",
    "chain", "mutation", "candidate", "antibody", "format",
    "source_sample_id", "sequence_entry_id",
}

# 源里表示「空」的哨兵。base.NullReason 把它与真空区分开：
# 朴素非空判断会把填充率算虚高。
_SENTINELS = {"", "na", "n/a", "nan", "none", "null", "-", "--"}


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return str(v).strip().lower() in _SENTINELS


def _blank_reason(v: Any) -> str:
    """真空 vs 哨兵。两者都是「数据缺失」，但必须能分开统计。"""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return NullReason.SOURCE_EMPTY
    return NullReason.SENTINEL_EMPTY


def _clean(v: Any) -> str | None:
    """取字符串值。metadata.PDB 的值带前导制表符（例 "\\t6v4p"），mapping 要求 strip。"""
    if _is_blank(v):
        return None
    return str(v).strip()


def _norm_ws(s: str) -> str:
    """把栏名里的换行/连续空白压成单空格再 strip。

    [Field Dictionary] 记的 field_name 是压过空白的，而工作簿真实表头带换行与
    首尾空格（实测 Jain et al.(2024)：'AC-SINS \\n∆λmax (nm)'、' PSR'、
    'SEC % Monomer '）。不压就查不到字典行。
    """
    return re.sub(r"\s+", " ", str(s)).strip()


def _slug(s: str) -> str:
    """栏名 → [Assay Endpoint Dictionary].Original_Field_Key 的写法。

    实测该表用的是 slug 而非原始栏名：
      'Tm(Negated)'          → tm_negated
      'HIC.16'               → hic_16
      'Fab Tm by DSF (°C)'   → fab_tm_by_dsf_c
      'AC-SINS \\n∆λmax (nm)' → ac_sins_max_nm   （∆λ 非 ASCII，与其他分隔符一样丢弃）
    """
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def _to_float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _check_columns(where: str, declared: list[str], actual: list[str]) -> None:
    """mapping 声明的栏名 vs 档案实际栏名。对不上就停。

    骨架宁可在这里炸，也不要带着错位的栏名往下跑 —— 后者会静默产出错数据。
    """
    d, a = list(declared), list(actual)
    missing = [c for c in d if c not in a]      # mapping 说有、档案没有
    extra = [c for c in a if c not in d]        # 档案有、mapping 没写
    if not missing and not extra:
        return
    raise ParseError(
        f"[栏名校验失败] {where}\n"
        f"  mapping 声明的栏（{len(d)}）：{d}\n"
        f"  档案实际的栏（{len(a)}）：{a}\n"
        f"  mapping 有 / 档案无（{len(missing)}）：{missing}\n"
        f"  档案有 / mapping 无（{len(extra)}）：{extra}\n"
        f"  → mapping 与 raw 快照已脱节，请先更新 docs/Mapping/dotad_to_binder.yaml，"
        f"不要改 parser 去迁就。"
    )


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
class DotadParser(SourceParser):
    """DOTAD 2.0 的三条产出线，对应 mapping Part 3 的三块 target。

    target 0 —— 实体行：sequences 左连 metadata，record_per_source: one
    target 1 —— 证据行：experimental 的三个 tidy format 分页，many
    target 2 —— 证据行：literature 的 29 个文献分页，many
    """

    mapping_id = "dotad_to_binder"
    source_dir = "dotad"

    # mapping Part 3 targets[] 的下标。三块 table 都是 binder.binder，
    # 只能按顺序区分，故钉在这里并在 __init__ 里断言。
    T_ENTITY, T_EXPERIMENTAL, T_LITERATURE = 0, 1, 2

    def __init__(self, mapping):
        super().__init__(mapping)
        if len(self.targets) != 3:
            raise ParseError(
                f"mapping 有 {len(self.targets)} 块 target，本 parser 按 3 块写"
                f"（实体 / experimental / literature）。targets 结构变了就得改这里。"
            )
        for i, want in ((self.T_EXPERIMENTAL, "many"), (self.T_LITERATURE, "many")):
            if self.targets[i].record_per_source != want:
                raise ParseError(
                    f"targets[{i}].record_per_source={self.targets[i].record_per_source!r}，"
                    f"预期 {want!r} —— 证据行必须一对多，否则会 collapse 掉多次观测"
                )
        self._cache: dict[str, pd.DataFrame] = {}
        self._field_dict: pd.DataFrame | None = None
        self._endpoint_dict: pd.DataFrame | None = None
        self._link: dict[str, dict] | None = None

    # ---------------- mapping 里的档案位置 ----------------
    def _datasets(self) -> dict:
        """读 mapping.raw["source_datasets"]。

        不用 base.Mapping.source_dataset —— 那个 property 读单数键，
        本 mapping 写的是复数（四个工作簿），调它必抛 ParseError。见档头 M1。
        """
        ds = self.mapping.raw.get("source_datasets")
        if not ds:
            raise ParseError(
                f"{self.mapping.path.name} 既无 source_datasets 也无 source_dataset，"
                f"parser 不知道读哪些 raw 档"
            )
        return ds

    def _path(self, key: str) -> Path:
        spec = self._datasets().get(key)
        if not spec or not spec.get("file"):
            raise ParseError(f"mapping.source_datasets 缺 {key}.file")
        p = ROOT / spec["file"]
        if not p.is_file():
            raise ParseError(f"{key} 指向 {p}，该档不存在")
        return p

    def _sheet(self, key: str, sheet: str) -> pd.DataFrame:
        ck = f"{key}::{sheet}"
        if ck not in self._cache:
            self._cache[ck] = pd.read_excel(
                self._path(key), sheet_name=sheet, engine="openpyxl"
            )
        return self._cache[ck]

    def _sheet_names(self, key: str) -> list[str]:
        return pd.ExcelFile(self._path(key), engine="openpyxl").sheet_names

    def input_files(self) -> list[tuple[Path, str]]:
        """交给 Interim.consume() 登记的 raw 档。data_dictionary 不入库但参与解析，也要登记。"""
        return [
            (self._path("metadata"), "metadata + sequences"),
            (self._path("experimental"), "experimental developability"),
            (self._path("literature"), "literature developability"),
            (self._path("data_dictionary"), "QC 边界与指标归一化，不入库"),
        ]

    # ---------------- data_dictionary：QC 边界 + 指标归一化 ----------------
    def _fd(self) -> pd.DataFrame:
        """[Field Dictionary]：逐 (source_sheet, field_name) 给 unit / 上下界。

        registry 与 mapping 都写明可直接拿来做 QC 边界检查，不必自己再推一遍。
        """
        if self._field_dict is None:
            df = self._sheet("data_dictionary", "Field Dictionary")
            df = df.copy()
            df["_sheet"] = df["source_sheet"].map(_norm_ws)
            df["_field"] = df["field_name"].map(_norm_ws)
            self._field_dict = df
        return self._field_dict

    def _field_spec(self, sheet: str, column: str) -> dict:
        df = self._fd()
        hit = df[(df["_sheet"] == _norm_ws(sheet)) & (df["_field"] == _norm_ws(column))]
        if hit.empty:
            return {}
        r = hit.iloc[0]
        return {
            "unit": _clean(r.get("unit")),
            "lower_bound": _to_float(r.get("lower_bound")),
            "upper_bound": _to_float(r.get("upper_bound")),
        }

    def _ed(self) -> pd.DataFrame:
        """[Assay Endpoint Dictionary]：跨文献指标归一化的唯一依据。

        实测 34 行（mapping Part 0 写 35，见档头 M6）。Original_Field_Key 是 slug，
        且 experimental 那侧记的是 *_avg（average 分页）的键 —— tidy format 分页
        的 hic_rt / tm1_nanodsf 等**不在**这张表里，只被首行的 (*, *) 通配行覆盖，
        而那行的 Harmonized_Endpoint 为空、Comparable_Flag 为 False。
        """
        if self._endpoint_dict is None:
            df = self._sheet("data_dictionary", "Assay Endpoint Dictionary").copy()
            df["_wb"] = df["Source_Workbook"].map(_norm_ws)
            df["_sheet"] = df["Source_Sheet"].map(_norm_ws)
            df["_key"] = df["Original_Field_Key"].map(
                lambda v: "*" if _norm_ws(v) == "*" else _slug(v)
            )
            self._endpoint_dict = df
        return self._endpoint_dict

    def _endpoint(self, workbook: str, sheet: str, column: str) -> dict | None:
        """查 Harmonized_Endpoint。精确 (sheet, key) 优先，其次通配行。查不到返回 None。"""
        df = self._ed()
        wb = df[df["_wb"] == _norm_ws(workbook)]
        if wb.empty:
            return None
        key = _slug(column)
        for cond in (
            (wb["_sheet"] == _norm_ws(sheet)) & (wb["_key"] == key),
            (wb["_sheet"] == "*") & (wb["_key"] == key),
            (wb["_sheet"] == _norm_ws(sheet)) & (wb["_key"] == "*"),
            (wb["_sheet"] == "*") & (wb["_key"] == "*"),
        ):
            hit = wb[cond]
            if not hit.empty:
                r = hit.iloc[0]
                return {
                    "matched_key": _clean(r.get("Original_Field_Key")),
                    "harmonized_endpoint": _clean(r.get("Harmonized_Endpoint")),
                    "endpoint_unit": _clean(r.get("Endpoint_Unit")),
                    "comparable_flag": bool(r.get("Comparable_Flag")),
                    "condition": _clean(r.get("Condition")),
                    "value_transform": _clean(r.get("Value_Transform")),
                    "notes": _clean(r.get("Notes")),
                }
        return None

    # ---------------- literature 的 [link] 分页 → citation ----------------
    def _links(self) -> dict[str, dict]:
        """分页名 → {name, PMID, address}。

        mapping 只说「由 [link] 分页按 sheet 名连接取得」，没给算法。实测两侧写法不同：
          分页 'Jain et al.(2024)'  ↔ link 'Jain （2024）'   （全角括号）
          分页 'Makowski et al.(2024)' ↔ link 'Makowski(2024)'
          分页 'Kraft et al. '      ↔ link 'kraft'          （尾随空格）
        故用一个可复现的机械归一：小写 → 去 "et al" → 只留 [a-z0-9]。
        对不上的不猜，citation 记 DERIVATION_FAILED。
        """
        if self._link is None:
            df = self._sheet("literature", "link")
            _check_columns("literature[link]", ["name", "PMID", "address"], list(df.columns))
            out = {}
            for _, r in df.iterrows():
                name = _clean(r["name"])
                if name:
                    out[self._link_key(name)] = {
                        "name": name,
                        "pmid": _clean(r["PMID"]),
                        "address": _clean(r["address"]),
                    }
            self._link = out
        return self._link

    @staticmethod
    def _link_key(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", re.sub(r"et\s*al\.?", "", str(s).lower()))

    # ======================================================================
    # iter_source_rows —— 读档、校验栏名、逐栏分类，再逐行吐出
    # ======================================================================
    def iter_source_rows(self) -> Iterator[dict]:
        """吐出带 `_block` 标签的源行。四种标签：

          entity        —— sequences 一行（含左连到的 metadata，可能为 None）
          experimental  —— tidy format 一行 + 该分页的指标栏分类结果
          literature    —— 文献分页一行 + 该分页的指标栏分类结果
          sheet_problem —— 分页级/栏级的问题，交 build_records 转成 out.reject()

        栏级问题在这里一次性算完（而不是逐行判断），否则 Adams 2,807 行 × 13 栏
        会写出上万条内容相同的 reject。
        """
        yield from self._iter_entity()
        yield from self._iter_experimental()
        yield from self._iter_literature()

    def _declared_inventory(self, section: str) -> list[str]:
        """mapping Part 1 source_field_inventory[section] 声明的栏名。

        条目里的 source 可能是列表（如 sequences 的 [hc_dna_sequence, lc_dna_sequence]
        合并成一条写），要展平。
        """
        inv = (self.mapping.raw.get("source_field_inventory") or {}).get(section)
        if not inv:
            raise ParseError(
                f"{self.mapping.path.name} 的 source_field_inventory 里没有 {section} —— "
                f"无从校验栏名"
            )
        cols: list[str] = []
        for item in inv:
            s = item.get("source")
            cols.extend(s if isinstance(s, list) else [s])
        return cols

    # ---------- (1) 实体行 ----------
    def _iter_entity(self) -> Iterator[dict]:
        md = self._sheet("metadata", "metadata")
        sq = self._sheet("sequences", "sequences")

        # mapping Part 1 把这两页的栏名逐条列全了，所以这里做**严格**校验：
        # 先比 mapping 声明 vs 档案实际（这一条是真正的时效性闸门），
        # 再比上次实测常量 vs 档案实际（上游改版的独立信号）。
        _check_columns("metadata 分页（mapping Part 1 vs 档案）",
                       self._declared_inventory("metadata"), list(md.columns))
        _check_columns("sequences 分页（mapping Part 1 vs 档案）",
                       self._declared_inventory("sequences"), list(sq.columns))
        _check_columns("metadata 分页（2026-08-24 实测基线 vs 档案）",
                       _METADATA_COLUMNS, list(md.columns))
        _check_columns("sequences 分页（2026-08-24 实测基线 vs 档案）",
                       _SEQUENCES_COLUMNS, list(sq.columns))

        # 填充率 0% 的两栏：栏在但全空。若哪天有值了，说明上游变了，值得知道。
        for col in _EMPTY_METADATA_COLUMNS:
            n = int(md[col].notna().sum())
            if n:
                yield {
                    "_block": "sheet_problem",
                    "_sheet": "metadata",
                    "_reason": "empty_column_now_populated",
                    "_detail": f"{col} 实测填充率应为 0.0%，本次读到 {n} 个非空值 —— "
                               f"mapping Part 1 的【实测告警】需复核",
                }

        md_by_id = {str(r["antibody_id"]): r for _, r in md.iterrows()}

        # mapping source_datasets.sequences.join_to_metadata：以 sequences 为主表左连。
        # 实测 metadata 的 4,100 个 id 是 sequences 9,845 个 id 的真子集，
        # 两侧 id 都无重复 → 交集上是 1:1，另有 5,745 条只有序列没有 metadata。
        for i, r in sq.iterrows():
            aid = str(r["antibody_id"])
            yield {
                "_block": "entity",
                "_sheet": "sequences",
                "_row": int(i),
                "antibody_id": aid,
                "_seq": r,
                "_md": md_by_id.get(aid),
            }

    # ---------- (2) experimental 证据行 ----------
    def _iter_experimental(self) -> Iterator[dict]:
        blk = self.targets[self.T_EXPERIMENTAL]
        # mapping source_datasets.experimental.note 与 targets[1].iterate_over 都写明：
        # 只取 tidy format，average 是同一批数据的派生统计量，两者都灌会重复计数。
        sheets = [s for s in self._sheet_names("experimental") if "tidy" in s.lower()]
        if len(sheets) != 3:
            raise ParseError(
                f"experimental 工作簿有 {len(sheets)} 个 tidy format 分页，"
                f"mapping targets[1].iterate_over 写的是三个：{sheets}"
            )

        want = self._declared_sources(blk)
        for sheet in sheets:
            df = self._sheet("experimental", sheet)
            if "antibody_id" not in df.columns:
                yield self._sheet_problem(sheet, "missing_record_key",
                                          f"mapping record_key 是 antibody_id，该分页栏为 {list(df.columns)}")
                continue

            plan, problems = self._plan_experimental(sheet, df, want)
            yield from problems
            for i, r in df.iterrows():
                yield {"_block": "experimental", "_sheet": sheet, "_row": int(i),
                       "antibody_id": _clean(r["antibody_id"]), "_r": r, "_plan": plan}

    @staticmethod
    def _declared_sources(blk: TargetBlock) -> dict[str, list[str]]:
        """target 块里 每个目标列 → 它声明的源栏名（原样，不做归一）。"""
        return {f.target: f.source_columns for f in blk.fields}

    def _plan_experimental(self, sheet: str, df: pd.DataFrame,
                           want: dict[str, list[str]]) -> tuple[dict, list[dict]]:
        """一次性把该分页的指标栏分成「可映射」与「不可映射」。"""
        cols = list(df.columns)
        plan: dict[str, dict] = {}
        problems: list[dict] = []

        # --- tm_celsius：mapping 规则明写「取 tm1_nanodsf 为主值；tonset 是起始温度
        #     不是 Tm，不得混填」。tm2/tm3 是另外的热转变，mapping 没给落点。
        for col in want.get("tm_celsius", []):
            if col not in cols:
                continue
            if col == "tm1_nanodsf":
                plan[col] = {"target": "tm_celsius", "kind": "numeric"}
            else:
                problems.append(self._sheet_problem(
                    sheet, "metric_declared_but_no_target_rule",
                    f"{col}：mapping targets[1].tm_celsius 只把 tm1_nanodsf 定为主值，"
                    f"{col} 无落点（tonset 明确「不得混填」，tm2/tm3 是另外的热转变）",
                    column=col, n_rows=int(df[col].notna().sum())))

        # --- hydrophobicity：R3 说这是本档最易出错处。源是保留时间（min），
        #     目标列无量纲。必须先经 Harmonized_Endpoint 归一化。
        for col in want.get("hydrophobicity", []):
            if col not in cols:
                continue
            ep = self._endpoint("dotad_experimental_developability_v2.0.xlsx", sheet, col)
            fs = self._field_spec(sheet, col)
            problems.append(self._sheet_problem(
                sheet, "endpoint_not_harmonized",
                f"{col}：[Assay Endpoint Dictionary] 对 tidy format 分页只有 (*,*) 通配行"
                f"（Harmonized_Endpoint 空、Comparable_Flag=False、注为「raw replicate-level "
                f"workbook … excluded from first-release primary benchmark labels」），"
                f"精确键只覆盖 average 分页的 {col}_avg。且 Value_Transform 为空，"
                f"没有从 {fs.get('unit')} 到无量纲 hydrophobicity 的换算。"
                f"按 mapping R3 不得直接灌入。",
                column=col, n_rows=int(df[col].notna().sum()),
                endpoint=ep, field_spec=fs))

        # --- aggregation：目标列是 text，mapping 规则「合成描述串」。
        #     只做精确栏名匹配 —— 见档头 M2，三个分页的 acsins 栏名写法不同，
        #     大小写/近名归并是猜，不做。
        for col in want.get("aggregation", []):
            if col in cols:
                plan[col] = {"target": "aggregation", "kind": "text"}
            else:
                near = [c for c in cols if _slug(c).startswith(_slug(col)[:12])]
                problems.append(self._sheet_problem(
                    sheet, "declared_column_absent_in_sheet",
                    f"mapping targets[1].aggregation 声明源栏 {col!r}，该分页没有。"
                    f"该分页里 slug 前缀相近的栏：{near}。"
                    f"不按相似度归并（registry 明令），交人决定。",
                    column=col, near_columns=near))

        # --- experiment_conditions 的组成部分：production_batch / run 只在第一个
        #     tidy 分页有（档头 M3）。不阻断，但要记下来。
        for col in want.get("experiment_conditions", []):
            if col in ("sheet_name", "metric_name"):
                continue
            if col not in cols:
                problems.append(self._sheet_problem(
                    sheet, "condition_part_absent",
                    f"experiment_conditions 声明含 {col!r}，该分页无此栏；"
                    f"组串时该位写 <缺栏>，不留空以免与「有栏但值空」混淆",
                    column=col))
        return plan, problems

    # ---------- (3) literature 证据行 ----------
    def _iter_literature(self) -> Iterator[dict]:
        blk = self.targets[self.T_LITERATURE]
        want = self._declared_sources(blk)
        self._links()  # 提前触发 link 分页的栏名校验

        sheets = [s for s in self._sheet_names("literature") if s.strip() != "link"]
        for sheet in sheets:
            df = self._sheet("literature", sheet)
            if "antibody_id" not in df.columns:
                # 实测只有 shanehsazzadeh et al. 这一页（首栏是 Candidate），见档头 M7。
                yield self._sheet_problem(
                    sheet, "missing_record_key",
                    f"mapping literature.record_key 是 antibody_id，该分页栏为 {list(df.columns)}；"
                    f"整页无法接入，不猜 Candidate 是否等价于 antibody_id",
                    n_rows=int(len(df)))
                continue

            plan, problems = self._plan_literature(sheet, df, want)
            yield from problems
            cite = self._citation_for(sheet)
            for i, r in df.iterrows():
                yield {"_block": "literature", "_sheet": sheet, "_row": int(i),
                       "antibody_id": _clean(r["antibody_id"]), "_r": r,
                       "_plan": plan, "_cite": cite}

    def _plan_literature(self, sheet: str, df: pd.DataFrame,
                         want: dict[str, list[str]]) -> tuple[dict, list[dict]]:
        """逐栏决定落到哪个目标列。栏级判断只做一次。"""
        plan: dict[str, dict] = {}
        problems: list[dict] = []
        s = sheet.strip()

        # kd_nm —— mapping 用 "分页.栏名" / "分页 的 栏名" 的散文写法声明源。
        # 只接受**精确**栏名。Jain et al.(2024) 的 'Octet KD (M)' 不存在（档头 M4）。
        for decl in want.get("kd_nm", []):
            d_sheet, d_col = self._split_declared(decl)
            if d_sheet is None or _norm_ws(d_sheet) != _norm_ws(s):
                continue
            if d_col in df.columns:
                plan[d_col] = {"target": "kd_nm", "kind": "numeric"}
            else:
                cand = [c for c in df.columns if "(M)" in str(c) or "[M]" in str(c)]
                problems.append(self._sheet_problem(
                    sheet, "declared_column_absent_in_sheet",
                    f"mapping targets[2].kd_nm 声明源 {decl!r}，该分页没有 {d_col!r} 这一栏。"
                    f"该分页带 (M)/[M] 的栏只有：{cand} —— 实测这两栏测的是对溶菌酶的结合"
                    f"（多反应性对照），不是抗体对自身靶点的亲和力，灌进 kd_nm 会污染字段。"
                    f"不代选，交人决定。",
                    column=d_col, candidate_columns=cand))

        # immunogenicity_risk —— 同样按精确栏名。
        for decl in want.get("immunogenicity_risk", []):
            d_sheet, d_col = self._split_declared(decl)
            if d_sheet is None or _norm_ws(d_sheet) != _norm_ws(s):
                continue
            if d_col in df.columns:
                plan[d_col] = {"target": "immunogenicity_risk", "kind": "text"}
            else:
                problems.append(self._sheet_problem(
                    sheet, "declared_column_absent_in_sheet",
                    f"mapping targets[2].immunogenicity_risk 声明源 {decl!r}，该分页无 {d_col!r}",
                    column=d_col))

        # tm_celsius —— mapping 的 source 是散文（「各分页的 Tm / Tm1 (C) / …等」），
        # 唯一可执行的依据是 rule_ref: harmonize_endpoint。所以逐栏查
        # [Assay Endpoint Dictionary]，只有 Harmonized_Endpoint == Tm 且单位 degC 才接。
        for col in df.columns:
            if col in plan or _slug(col) in _NON_METRIC_COLUMNS:
                continue
            ep = self._endpoint(
                "dotad_literature_developability_collection_v2.0.xlsx", sheet, col)
            if ep and ep.get("harmonized_endpoint") == "Tm" and ep.get("endpoint_unit") == "degC":
                plan[col] = {"target": "tm_celsius", "kind": "numeric", "endpoint": ep}
                continue
            problems.append(self._sheet_problem(
                sheet, "no_target_column_for_metric",
                (f"{col!r}：Harmonized_Endpoint="
                 f"{ep.get('harmonized_endpoint') if ep else None!r}，"
                 f"单位={ep.get('endpoint_unit') if ep else None!r} —— "
                 f"mapping targets[2] 未给该指标落点，且不得凭栏名相近并到别的指标"),
                column=col, n_rows=int(df[col].notna().sum()), endpoint=ep))
        return plan, problems

    @staticmethod
    def _split_declared(decl: str) -> tuple[str | None, str]:
        """把 mapping 里三种散文写法拆成 (分页名, 栏名)：

            "Adams et al..fit_KD_median [M]"      → ('Adams et al.', 'fit_KD_median [M]')
            "Jain et al.(2024) 的 Octet KD (M)"   → ('Jain et al.(2024)', 'Octet KD (M)')
            "marks et al. 分页的 %ADA response"    → ('marks et al.', '%ADA response')

        第三种带「分页」二字，要去掉，否则永远匹配不上真实分页名。
        """
        m = re.match(r"^(.*?)\s*(?:分页)?\s*的\s*(.+)$", decl)
        if m:
            return re.sub(r"\s*分页$", "", m.group(1)), m.group(2)
        m = re.match(r"^(.*et al\.\S*?)\.(.+)$", decl)
        if m:
            return m.group(1), m.group(2)
        return None, decl

    def _citation_for(self, sheet: str) -> dict:
        link = self._links().get(self._link_key(sheet))
        if not link:
            return {"text": None, "reason": NullReason.DERIVATION_FAILED,
                    "detail": f"[link] 分页里找不到与分页名 {sheet!r} 对应的行"}
        parts = [link["name"], link["pmid"], link["address"]]
        if not link["pmid"]:
            # 实测 shanehsazzadeh / garbinski 两行的 PMID 与 address 为空。
            return {"text": link["name"], "reason": None, "link": link,
                    "detail": "[link] 该行无 PMID/address，citation 只有作者名"}
        return {"text": " | ".join(p for p in parts if p), "reason": None, "link": link}

    @staticmethod
    def _sheet_problem(sheet: str, reason: str, detail: str, **info) -> dict:
        return {"_block": "sheet_problem", "_sheet": sheet,
                "_reason": reason, "_detail": detail, **info}

    # ======================================================================
    # build_records
    # ======================================================================
    def build_records(self, row: dict, out: Interim) -> Iterator[Record]:
        blk = row["_block"]
        if blk == "sheet_problem":
            out.reject(row["_reason"], **{k: v for k, v in row.items()
                                          if k not in ("_block", "_reason")})
            return
        if blk == "entity":
            yield from self._entity_record(row, out)
        elif blk == "experimental":
            yield from self._experimental_records(row, out)
        elif blk == "literature":
            yield from self._literature_records(row, out)
        else:
            out.reject("unknown_block", block=blk)

    # ---------- (1) 实体行 ----------
    def _entity_record(self, row: dict, out: Interim) -> Iterator[Record]:
        blk = self.targets[self.T_ENTITY]
        seq, md, aid = row["_seq"], row["_md"], row["antibody_id"]
        rec = Record(table=blk.table, entity_key={"antibody_id": aid})
        src = {"source_file": self._path("metadata").name, "row": row["_row"]}

        rec.set("source_type", "公开库", method="constant")
        rec.set("evidence_level", "同行评议", method="constant",
                note="mapping targets[0]：按源定固定值")
        rec.set("source_id", aid, method="direct", sheet="sequences",
                src_column="antibody_id", **src)

        # 序列。sequences 是主表，一定有。
        for col, tgt in (("VH", "vh_seq"), ("VL", "vl_seq")):
            v = _clean(seq[col])
            if v is None:
                # VL 空不得默认判为 VHH —— mapping Part 1 明写，须与 Format 交叉判断。
                rec.absent(tgt, _blank_reason(seq[col]), sheet="sequences", src_column=col, **src)
            else:
                rec.set(tgt, v, method="direct", sheet="sequences", src_column=col, **src)

        if md is None:
            # 实测 5,745 条 sequences 行在 metadata 里没有对应记录。
            # 这不是抽取失败，是本源结构上这条记录只有序列。
            for tgt in ("name_code", "format", "target_antigen", "germline",
                        "structure_template", "development_stage", "applicable_scenario",
                        "immunogenicity_risk", "citation"):
                rec.absent(tgt, NullReason.SOURCE_EMPTY,
                           note="该 antibody_id 在 metadata 分页无对应行（序列孤儿）")
            yield rec
            return

        msrc = {"source_file": self._path("metadata").name, "sheet": "metadata"}
        self._direct(rec, md, "antibody_name", "name_code", msrc)
        self._direct(rec, md, "Species", "germline", msrc)
        self._direct(rec, md, "Clinical indication", "applicable_scenario", msrc)

        # format —— rule_ref: derive_binder_format
        self._set_format(rec, md, seq, msrc)

        # target_antigen —— rule_ref: normalize_antigen_name 只有描述没有算法，
        # 且 mapping Part 1 写「需逐条判断」。原值 strip 后入库，并标明规则未执行。
        raw_t = _clean(md["Target"])
        if raw_t is None:
            rec.absent("target_antigen", _blank_reason(md["Target"]), src_column="Target", **msrc)
        else:
            rec.set("target_antigen", raw_t, method="derived",
                    rule_ref="normalize_antigen_name", rule_applied=False,
                    src_column="Target",
                    note="normalize_antigen_name 只给了描述未给算法，mapping 亦写明"
                         "「\"/\" 分隔的需逐条判断」——本轮原样保留，待归一化阶段处理",
                    **msrc)

        # structure_template —— 值带前导制表符（实测 "\t6v4p"），mapping 要求 strip
        pdb = _clean(md["PDB"])
        if pdb is None:
            rec.absent("structure_template", _blank_reason(md["PDB"]), src_column="PDB", **msrc)
        else:
            rec.set("structure_template", pdb, method="derived", src_column="PDB",
                    rule="strip 前导制表符", raw=repr(md["PDB"]), **msrc)

        # development_stage —— 两栏合成，且必须注明 est_status 的截止日
        hi, est = _clean(md["Highest_Clin_Trial"]), _clean(md["est_status_asof_feb2025"])
        if hi is None and est is None:
            rec.absent("development_stage", NullReason.SOURCE_EMPTY,
                       src_columns=["Highest_Clin_Trial", "est_status_asof_feb2025"], **msrc)
        else:
            rec.set("development_stage", f"{hi or 'NA'} / {est or 'NA'} (as of 2025-02)",
                    method="derived", src_columns=["Highest_Clin_Trial", "est_status_asof_feb2025"],
                    rule='"{Highest_Clin_Trial} / {est_status} (as of 2025-02)"',
                    note="est_status 截至 2025-02，栏名自带截止日，已过时约 18 个月", **msrc)

        # immunogenicity_risk —— "ADA {value}%"，保留原值
        ada = _clean(md["ADAs_rate"])
        if ada is None:
            rec.absent("immunogenicity_risk", _blank_reason(md["ADAs_rate"]),
                       src_column="ADAs_rate", **msrc)
        else:
            rec.set("immunogenicity_risk", f"ADA {ada}%", method="derived",
                    src_column="ADAs_rate", raw=ada, rule='"ADA {ADAs_rate}%"', **msrc)

        # citation —— PDB_reference + ADAs_reference
        cites = [c for c in (_clean(md["PDB_reference"]), _clean(md["ADAs_reference"])) if c]
        if cites:
            rec.set("citation", "; ".join(cites), method="derived",
                    src_columns=["PDB_reference", "ADAs_reference"], **msrc)
        else:
            rec.absent("citation", NullReason.SOURCE_EMPTY,
                       src_columns=["PDB_reference", "ADAs_reference"], **msrc)
        yield rec

    @staticmethod
    def _direct(rec: Record, r, column: str, target: str, src: dict) -> None:
        v = _clean(r[column])
        if v is None:
            rec.absent(target, _blank_reason(r[column]), src_column=column, **src)
        else:
            rec.set(target, v, method="direct", src_column=column, **src)

    def _set_format(self, rec: Record, md, seq, src: dict) -> None:
        spec = self.mapping.rule_refs.get("derive_binder_format") or {}
        vmap = spec.get("value_map") or {}
        fallback = spec.get("fallback", "其他")
        raw = _clean(md["Format"])
        has_vl = _clean(seq["VL"]) is not None
        if raw is None:
            rec.absent("format", _blank_reason(md["Format"]), src_column="Format", **src)
            return
        mapped = vmap.get(raw)
        prov = {"method": "derived", "rule_ref": "derive_binder_format",
                "src_columns": ["Format", "VL"], "raw": raw, "vl_present": has_vl, **src}
        if mapped is None:
            # 双特异等 103 个取值里 value_map 没覆盖的，按 mapping 落 fallback。
            prov["note"] = ("value_map 未覆盖该取值，按 rule_refs.fallback 落 "
                            f"{fallback}；双特异分页展开规则 mapping 标注「待定」")
            prov["pending"] = "bispecific_expansion_undecided" if "ispecific" in raw else None
            rec.set("format", fallback, **prov)
            return
        if mapped == "VHH" and has_vl:
            # Format 说是单域但有 VL —— 两侧矛盾，不静默采信任一方。
            prov["note"] = "Format 判为 VHH 但 sequences 有 VL，两侧矛盾，落 fallback"
            rec.set("format", fallback, **prov)
            return
        rec.set("format", mapped, **prov)

    # ---------- (2) experimental 证据行 ----------
    def _experimental_records(self, row: dict, out: Interim) -> Iterator[Record]:
        blk = self.targets[self.T_EXPERIMENTAL]
        sheet, r, plan, aid = row["_sheet"], row["_r"], row["_plan"], row["antibody_id"]
        if not aid:
            out.reject(NullReason.SOURCE_EMPTY, sheet=sheet, row=row["_row"],
                       problems=["antibody_id 为空，无法定 entity_key"])
            return
        rep = _clean(r["technical_replicate"]) if "technical_replicate" in r.index else None
        src = {"source_file": self._path("experimental").name, "sheet": sheet, "row": row["_row"]}

        # 「每行 × 每个指标栏」→ 一个指标栏一条 Record。绝不 collapse 成一条。
        for col, how in plan.items():
            raw = r[col] if col in r.index else None
            if _is_blank(raw):
                continue
            fs = self._field_spec(sheet, col)
            rec = Record(table=blk.table, entity_key={"antibody_id": aid})
            rec.set("source_type", "公开库", method="constant")
            rec.set("evidence_level", "同行评议", method="constant")
            rec.set("source_id", f"{aid}|{sheet}|{col}|rep{rep or 'NA'}", method="derived",
                    rule='"{antibody_id}|{sheet}|{metric}|rep{n}"', **src)

            if how["kind"] == "numeric":
                v = _to_float(raw)
                if v is None:
                    out.reject(NullReason.DERIVATION_FAILED, sheet=sheet, row=row["_row"],
                               column=col, raw=str(raw), problems=["非数值"])
                    continue
                bad = self._out_of_bounds(v, fs)
                if bad:
                    # [Field Dictionary] 的 lower/upper_bound 直接当 QC 边界，
                    # registry 与 mapping 都写明可照用。
                    out.reject(NullReason.VALIDATION_FAILED, sheet=sheet, row=row["_row"],
                               column=col, value=v, problems=[bad])
                    continue
                rec.set(how["target"], v, method="derived", src_column=col,
                        unit_from=fs.get("unit"),
                        note="源单位已是 °C，与 tm_celsius 一致，无需换算",
                        qc_bounds=[fs.get("lower_bound"), fs.get("upper_bound")], **src)
            else:
                unit = fs.get("unit")
                rec.set(how["target"], f"{col}={raw}" + (f" {unit}" if unit else ""),
                        method="derived", src_column=col, raw=str(raw), unit_from=unit,
                        rule="合成描述串", **src)

            rec.set("experiment_conditions",
                    self._conditions_experimental(sheet, col, r), method="derived", **src)
            yield rec

    @staticmethod
    def _out_of_bounds(v: float, fs: dict) -> str | None:
        lo, hi = fs.get("lower_bound"), fs.get("upper_bound")
        if lo is not None and v < lo:
            return f"{v} < [Field Dictionary].lower_bound {lo}"
        if hi is not None and v > hi:
            return f"{v} > [Field Dictionary].upper_bound {hi}"
        return None

    @staticmethod
    def _conditions_experimental(sheet: str, col: str, r) -> str:
        """mapping：[sheet_name, metric_name, production_batch, run, technical_replicate]。

        production_batch / run 只有第一个 tidy 分页有（档头 M3）。缺栏写 <缺栏>，
        与「有栏但值空」区分开。这一列 required: true。
        """
        parts = [f"sheet={sheet}", f"metric={col}"]
        for k in ("production_batch", "run", "technical_replicate"):
            if k not in r.index:
                parts.append(f"{k}=<缺栏>")
            else:
                parts.append(f"{k}={_clean(r[k]) or '<空>'}")
        return "; ".join(parts)

    # ---------- (3) literature 证据行 ----------
    def _literature_records(self, row: dict, out: Interim) -> Iterator[Record]:
        blk = self.targets[self.T_LITERATURE]
        sheet, r, plan, aid = row["_sheet"], row["_r"], row["_plan"], row["antibody_id"]
        if not aid:
            out.reject(NullReason.SOURCE_EMPTY, sheet=sheet, row=row["_row"],
                       problems=["antibody_id 为空，无法定 entity_key"])
            return
        cite = row["_cite"]
        pmid = (cite.get("link") or {}).get("pmid")
        src = {"source_file": self._path("literature").name, "sheet": sheet, "row": row["_row"]}
        kd_rule = next((f for f in blk.fields if f.target == "kd_nm"), None)

        for col, how in plan.items():
            raw = r[col] if col in r.index else None
            if _is_blank(raw):
                continue
            ep = how.get("endpoint") or {}
            rec = Record(table=blk.table, entity_key={"antibody_id": aid})
            rec.set("source_type", "文献", method="constant",
                    note="原始出处是具体文献，不是公开库整编")
            rec.set("evidence_level", self._evidence_level(sheet, col), method="derived",
                    rule_ref="derive_evidence_level_literature", sheet=sheet, src_column=col)
            rec.set("source_id", f"{pmid or sheet}|{aid}|{col}", method="derived", **src)

            if cite["text"]:
                rec.set("citation", cite["text"], method="derived",
                        rule="由 literature 工作簿的 [link] 分页按 sheet 名连接取得",
                        note=cite.get("detail"))
            else:
                rec.absent("citation", cite["reason"], detail=cite["detail"])

            if how["target"] == "kd_nm":
                v = _to_float(raw)
                if v is None or v <= 0:
                    out.reject(NullReason.DERIVATION_FAILED, sheet=sheet, row=row["_row"],
                               column=col, raw=str(raw), problems=["KD 非正数值"])
                    continue
                # 源单位 M，目标列 kd_nm 是 nM → ×1e9。unit_from 必须记进 provenance。
                unit_from = (kd_rule.extra.get("unit_from") if kd_rule else None) or "M"
                rec.set("kd_nm", v * 1e9, method="derived", src_column=col,
                        unit_from=unit_from, unit_to="nM", factor=1e9,
                        raw=v, rule="nM = 原值 × 1e9", **src)
            elif how["target"] == "tm_celsius":
                v = _to_float(raw)
                if v is None:
                    out.reject(NullReason.DERIVATION_FAILED, sheet=sheet, row=row["_row"],
                               column=col, raw=str(raw), problems=["非数值"])
                    continue
                # [Assay Endpoint Dictionary].Value_Transform 实测只有一个取值 'negate'
                # （Jain et al. 的 Tm(Negated)，原值为负）。字典说要转就转，不自作主张。
                transform = ep.get("value_transform")
                if transform == "negate":
                    v = -v
                elif transform:
                    out.reject("unknown_value_transform", sheet=sheet, row=row["_row"],
                               column=col, value_transform=transform,
                               problems=["[Assay Endpoint Dictionary] 给了本 parser 不认识的"
                                         "Value_Transform，不猜其含义"])
                    continue
                rec.set("tm_celsius", v, method="derived", src_column=col,
                        rule_ref="harmonize_endpoint",
                        harmonized_endpoint=ep.get("harmonized_endpoint"),
                        unit_from=ep.get("endpoint_unit"), value_transform=transform,
                        comparable_flag=ep.get("comparable_flag"), raw=str(raw), **src)
            else:  # immunogenicity_risk，text
                rec.set("immunogenicity_risk", f"ADA {_clean(raw)}%", method="derived",
                        src_column=col, raw=str(raw),
                        note='沿用 mapping targets[0] 的 "ADA {value}%" 写法', **src)

            rec.set("experiment_conditions",
                    "; ".join([
                        f"sheet={sheet}", f"metric={col}",
                        f"harmonized_endpoint={ep.get('harmonized_endpoint') or '<未覆盖>'}",
                        f"endpoint_unit={ep.get('endpoint_unit') or '<未覆盖>'}",
                        f"condition={ep.get('condition') or '<无>'}",
                    ]), method="derived", **src)
            yield rec

    @staticmethod
    def _evidence_level(sheet: str, column: str) -> str:
        """rule_refs.derive_evidence_level_literature。

        填错会让 source_weight 从 0.2 抬到 0.7，直接污染下游打分（mapping R4）。
        """
        if sheet.strip() in ("Hebditch et al.", "Bailly et al."):
            return "模型预测"
        return "模型预测" if str(column).strip().endswith(".pred") else "同行评议"

    # assign_uid() / should_include() 刻意不覆写 ——
    # base 里它们抛 Undecided("Q2") / Undecided("Q4")。业务侧未定，
    # 猜一个比留缺口更糟。run() 跑到那里停下是预期行为，不是 bug。
