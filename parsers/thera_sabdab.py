"""Thera-SAbDab → binder.binder。

可执行规格的唯一来源是 docs/Mapping/thera_sabdab_to_binder.yaml：
    Part 3 targets 两块（(1) 单特异一行=1 条、(2) 双特异一行=2 条）
    Part 4 rule_refs 三条派生规则
本档只实现这些；mapping 没写的一律不补（缺口宁可显式留着，也不猜一个值）。

未决的 assign_uid() / should_include() 不在这里覆写 —— 它们在 base 里
抛 Undecided("Q2") / Undecided("Q4")，那是有意为之的停止点。
"""
from __future__ import annotations

import csv
from typing import Iterator

from .base import (
    ROOT,
    Interim,
    NullReason,
    ParseError,
    Record,
    SourceParser,
)

# 栏名原样照抄档头，含空格、撇号、括号。
# mapping Part 1 明写「读取时勿改写」，一旦改写就与 mapping / registry 的字段清单对不上。
COL_NAME = "Therapeutic"
COL_FORMAT = "Format"
COL_CLIN_TRIAL = "Highest_Clin_Trial (Feb '25)"
COL_EST_STATUS = "Est. Status"
COL_VH = "HeavySequence"
COL_VL = "LightSequence"
COL_VH2 = "HeavySequence(ifbispec)"
COL_VL2 = "LightSequence(ifbispec)"
COL_YEAR_PROPOSED = "Year Proposed"
COL_YEAR_RECOMMENDED = "Year Recommended"
COL_TARGET = "Target"
COL_NOTES = "Notes"
COL_GENETICS = "Genetics (Bispecifics delimited with semicolon)"

#: pick_best_structure 的回退顺序：相似度高的优先。见 Part 4。
STRUCTURE_COLUMNS = ("100% SI Structure", "99% SI Structure", "95-98% SI Structure")
#: 写进 experiment_conditions 的档位标签 —— Part 4 note：「采用的档位必须写进
#: experiment_conditions，否则下游无法判断结构可信度」。
STRUCTURE_TIERS = {
    "100% SI Structure": "100%",
    "99% SI Structure": "99%",
    "95-98% SI Structure": "95-98%",
}

#: 三个 Conditions 栏 → 状态前缀。Part 3 (1) applicable_scenario 的规则。
CONDITION_COLUMNS = (
    ("Conditions Approved", "Approved"),
    ("Conditions Active", "Active"),
    ("Conditions Discontinued", "Discontinued"),
)

#: 本源用字串 "na" 表示缺失（mapping Part 1 的 fill 就是按「'na' 计为空」算的）。
#: base.NullReason.SENTINEL_EMPTY 的定义里点名了 "na"，所以它归 SENTINEL_EMPTY 而非 SOURCE_EMPTY。
NA_TOKEN = "na"


# --------------------------------------------------------------------------
# Part 4 —— 派生规则
# --------------------------------------------------------------------------
#: mapping Part 4 derive_binder_format.value_map，原样照抄，不增不减。
FORMAT_VALUE_MAP = {
    "Whole mAb": "IgG",
    "Whole mAb ADC": "IgG",
    "Whole mAb Fusion": "IgG",
    "Whole mAb Radiolabelled": "IgG",
    "Fab": "Fab",
    "scFv": "scFv",
    "Bispecific scFv": "scFv",
    "VHH": "VHH",
}
FORMAT_FALLBACK = "其他"


def derive_binder_format(raw_format: str | None) -> str | None:
    """Format（实测 104 个取值）→ binder.binder_format 五值枚举。

    双特异行的两个 arm 共用整栏值：Part 4 note 说「两个 arm 可能 format 不同
    （如 "Bispecific Mixed mAb and scFv"），需逐 arm 判定」，但没给「哪个 arm 是 mAb、
    哪个是 scFv」的判定规则。没有规则就不猜 —— 整栏值落 value_map，落不中走 fallback。
    实测双特异那 157 行的 Format 全部不在 value_map 里（Bispecific mAb 50、
    Bispecific Mixed mAb and scFv 21 …），所以两个 arm 都会得到「其他」。
    """
    if raw_format is None:
        return None
    return FORMAT_VALUE_MAP.get(raw_format, FORMAT_FALLBACK)


def normalize_antigen_name(raw_target: str | None) -> list[str]:
    """Target → 靶点列表。两种分隔符语义完全不同，见 Part 4 / Part 1。

    ";" 是真多靶点，拆开（CDH17;CD3E → ["CDH17", "CD3E"]）；
    "/" 是同一靶点的别名，不拆（MUC16/CA125 → ["MUC16/CA125"]，仍是一个靶点）。

    别名段整串保留而不挑一个规范名：mapping 没给别名优选表，
    挑哪个当规范名是未定的，硬挑一个就是编造。归一化到单一名称留给实体归并阶段。
    """
    if raw_target is None:
        return []
    return [seg.strip() for seg in raw_target.split(";") if seg.strip()]


def pick_best_structure(row: dict) -> tuple[str | None, str | None, str]:
    """三个 SI Structure 栏按 100% → 99% → 95-98% 回退取值。

    返回 (结构值, 采用的相似度档位, null_reason)；取到值时 null_reason 为 ""。

    实测这三栏 100% 非空，值大量是字串 "None"（765/900/910 行）与 "None;None"
    （122/141/128 行）而不是空值 —— 朴素非空判断会把填充率算成 100%，
    mapping Part 1 记的 32.5% / 20.6% / 19.7% 也仍把 "None;None" 当成了有值。
    去掉哨兵后的真实填充率是 21.7% / 8.1% / 8.4%。见 mapping R4。
    """
    saw_sentinel = False
    for col in STRUCTURE_COLUMNS:
        value, reason = _read(row, col)
        if value is None:
            saw_sentinel = saw_sentinel or reason == NullReason.SENTINEL_EMPTY
            continue
        # "None;None" 是双特异行两个 arm 都没结构；"None;6bi0:HL" 是只有第二个 arm 有。
        # 全段皆 "None" 才算缺失。
        if all(seg.strip() == "None" for seg in value.split(";")):
            saw_sentinel = True
            continue
        return value, STRUCTURE_TIERS[col], ""
    return None, None, NullReason.SENTINEL_EMPTY if saw_sentinel else NullReason.SOURCE_EMPTY


# --------------------------------------------------------------------------
# 取值小工具
# --------------------------------------------------------------------------
def _read(row: dict, col: str) -> tuple[str | None, str]:
    """取一栏，返回 (值, null_reason)。有值时 null_reason 为 ""。

    真空与哨兵 "na" 分开记：CLAUDE.md 要求「数据缺失」在 interim 层可辨识，
    而 base 把 "na" 这类占位字串归到 SENTINEL_EMPTY。
    """
    raw = row.get(col)
    if raw is None:
        raise ParseError(f"源档缺少栏位 `{col}` —— 档头与 mapping Part 1 的 24 栏清单不一致")
    value = raw.strip()
    if not value:
        return None, NullReason.SOURCE_EMPTY
    if value.lower() == NA_TOKEN:
        return None, NullReason.SENTINEL_EMPTY
    return value, ""


def _put(rec: Record, column: str, value: str | None, reason: str, **prov) -> None:
    """有值就 set，没值就 absent + 原因。两条路都带上 provenance。"""
    if value is None:
        rec.absent(column, reason, **prov)
    else:
        rec.set(column, value, **prov)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
class TheraSabDabParser(SourceParser):
    """Thera-SAbDab SeqStruc 全库 CSV → binder.binder。"""

    mapping_id = "thera_sabdab_to_binder"
    source_dir = "therasabdab"

    # --- 读源 ---
    @property
    def source_path(self):
        return ROOT / self.mapping.source_dataset["file"]

    def iter_source_rows(self) -> Iterator[dict]:
        """按 mapping Part 0 的 source_dataset 读 CSV，原始栏名逐行吐出。

        encoding 必须走 mapping 声明的 utf-8-sig：档首有 BOM，
        用 utf-8 读会让首栏名变成 "\\ufeffTherapeutic"，后续所有按栏名取值全落空。
        """
        ds = self.mapping.source_dataset
        path = self.source_path
        if not path.is_file():
            raise ParseError(f"raw 档不存在：{path}（先跑 downloader）")
        with path.open(encoding=ds.get("encoding", "utf-8"), newline="") as fh:
            yield from csv.DictReader(fh)

    # --- 建记录 ---
    def build_records(self, row: dict, out: Interim) -> Iterator[Record]:
        name, name_reason = _read(row, COL_NAME)
        if name is None:
            # Therapeutic 同时是 source_id(required) 与 entity_key，没有它这行无从落地。
            out.reject(NullReason.DERIVATION_FAILED,
                       column=COL_NAME, detail=name_reason, row_target=row.get(COL_TARGET))
            return

        # Part 3 两块的分流条件就是这一栏空不空。
        vh2, _ = _read(row, COL_VH2)
        if vh2 is None:
            yield from self._build_monospecific(row, name)
        else:
            yield from self._build_bispecific(row, name, out)

    # ---------- (1) 单特异：一行 = 一个 binder ----------
    def _build_monospecific(self, row: dict, name: str) -> Iterator[Record]:
        rec = Record(table="binder.binder", entity_key={COL_NAME: name})
        self._fill_shared(rec, row, name)

        rec.set("source_id", name, source=[COL_NAME], method="direct")

        vh, vh_reason = _read(row, COL_VH)
        _put(rec, "vh_seq", vh, vh_reason, source=[COL_VH], method="direct")
        vl, vl_reason = _read(row, COL_VL)
        _put(rec, "vl_seq", vl, vl_reason, source=[COL_VL], method="direct")

        germline, germline_reason = _read(row, COL_GENETICS)
        _put(rec, "germline", germline, germline_reason,
             source=[COL_GENETICS], method="direct")

        target, target_reason = _read(row, COL_TARGET)
        antigens = normalize_antigen_name(target)
        prov = dict(source=[COL_TARGET], method="derived", rule_ref="normalize_antigen_name")
        if len(antigens) == 1:
            rec.set("target_antigen", antigens[0], **prov)
        else:
            # 单特异行却拆出多个靶点段，mapping 没定这种情况该配哪一个
            # （实测 1 行：Pamlectabart，Target="TNFRSF17/CD269/BCMA/TNFRSF13A;CD3E"，
            #  但 HeavySequence(ifbispec) 为空）。不猜，记成派生失败。
            rec.absent("target_antigen",
                       target_reason or NullReason.DERIVATION_FAILED, **prov)

        yield rec

    # ---------- (2) 双特异：一行 = 两个 binder ----------
    def _build_bispecific(self, row: dict, name: str, out: Interim) -> Iterator[Record]:
        # 序列组数固定按重链算：实测 HeavySequence(ifbispec) 13.9% 非空、
        # LightSequence(ifbispec) 12.3% 非空，18 行是「有重链无轻链」的第二臂
        # （可能是 VHH 臂）。按轻链算会整个漏掉这 18 行的 arm2。见 mapping R3。
        arms = ((COL_VH, COL_VL), (COL_VH2, COL_VL2))

        target, _ = _read(row, COL_TARGET)
        antigens = normalize_antigen_name(target)
        if len(antigens) != len(arms):
            # R3 的硬要求：段数与序列组数不一致就整行判抽取失败，
            # 绝不按顺序硬配 —— 配错了等于给 binder 挂上错误靶点，比缺一条记录糟得多。
            out.reject(NullReason.DERIVATION_FAILED,
                       therapeutic=name,
                       detail="Target 的 ';' 段数与非空序列组数不一致，不得按顺序硬配",
                       target=target, n_antigens=len(antigens), n_arms=len(arms))
            return

        germline, germline_reason = _read(row, COL_GENETICS)
        germline_segs = [s.strip() for s in germline.split(";")] if germline else []

        for index, (vh_col, vl_col) in enumerate(arms):
            arm_no = index + 1
            rec = Record(table="binder.binder",
                         entity_key={COL_NAME: name, "arm_index": arm_no})
            self._fill_shared(rec, row, name)

            rec.set("source_id", f"{name}#arm{arm_no}",
                    source=[COL_NAME, "arm_index"], method="derived",
                    rule='"{Therapeutic}#arm{1|2}"')

            vh, vh_reason = _read(row, vh_col)
            _put(rec, "vh_seq", vh, vh_reason, source=[vh_col], method="derived", arm=arm_no)
            vl, vl_reason = _read(row, vl_col)
            _put(rec, "vl_seq", vl, vl_reason, source=[vl_col], method="derived", arm=arm_no)

            rec.set("target_antigen", antigens[index],
                    source=[COL_TARGET], method="derived",
                    rule_ref="normalize_antigen_name", arm=arm_no)

            # Genetics 同样按 ";" 拆、第 n 段配第 n 组。段数对不上就只失这一个字段
            # （实测 8 行：6 行只有一段、2 行是 "na"）——
            # mapping 只把「整行判失败」绑在 Target 上，没绑在 Genetics 上，不越权扩大。
            gprov = dict(source=[COL_GENETICS], method="derived", arm=arm_no)
            if len(germline_segs) == len(arms):
                seg = germline_segs[index]
                is_na = not seg or seg.lower() == NA_TOKEN
                _put(rec, "germline", None if is_na else seg,
                     NullReason.SENTINEL_EMPTY if seg else NullReason.SOURCE_EMPTY, **gprov)
            elif germline is None:
                rec.absent("germline", germline_reason, **gprov)
            else:
                rec.absent("germline", NullReason.DERIVATION_FAILED,
                           detail=f"Genetics 拆出 {len(germline_segs)} 段，与 {len(arms)} 个 arm 不符",
                           **gprov)

            yield rec

    # ---------- 两块共用的字段 ----------
    def _fill_shared(self, rec: Record, row: dict, name: str) -> None:
        """Part 3 (2) note：「其余字段与 (1) 相同，两个 arm 共用」。"""
        rec.set("source_type", "公开库", method="constant")
        # 业务侧 2026-08-20 决定：按源定固定值。本源虽含临床阶段，
        # 那是 development_stage 的内容，不是 evidence_level。
        rec.set("evidence_level", "同行评议", method="constant")
        rec.set("name_code", name, source=[COL_NAME], method="direct")

        raw_format, format_reason = _read(row, COL_FORMAT)
        _put(rec, "format", derive_binder_format(raw_format), format_reason,
             source=[COL_FORMAT], method="derived", rule_ref="derive_binder_format")

        structure, tier, structure_reason = pick_best_structure(row)
        _put(rec, "structure_template", structure, structure_reason,
             source=list(STRUCTURE_COLUMNS), method="derived",
             rule_ref="pick_best_structure", si_tier=tier)

        self._fill_development_stage(rec, row)
        self._fill_applicable_scenario(rec, row)
        self._fill_citation(rec, row, name)
        self._fill_experiment_conditions(rec, row, tier)

    def _fill_development_stage(self, rec: Record, row: dict) -> None:
        trial, trial_reason = _read(row, COL_CLIN_TRIAL)
        status, status_reason = _read(row, COL_EST_STATUS)
        prov = dict(source=[COL_CLIN_TRIAL, COL_EST_STATUS], method="derived",
                    rule='"{Highest_Clin_Trial} / {Est. Status} (as of 2025-02)"')
        if trial is None or status is None:
            rec.absent("development_stage", trial_reason or status_reason, **prov)
            return
        # "(as of 2025-02)" 是模板的一部分，不是修饰：本源已停更，栏名自带截止日
        # Feb '25，资料比现在旧约 18 个月，不注明就会被当成当前状态。见 R1。
        rec.set("development_stage", f"{trial} / {status} (as of 2025-02)", **prov)

    def _fill_applicable_scenario(self, rec: Record, row: dict) -> None:
        """三个 Conditions 栏按 ";" 拆分后逐项加状态前缀合并。

        逐项加前缀（而不是一栏一个前缀）是为了让 ";" 只有一种含义：
        "Approved: A; Approved: B; Active: C" 里每一段都自带状态，
        一栏一前缀的写法在栏内含多个适应症时会把状态归属弄丢。
        """
        items, reasons = [], []
        for col, label in CONDITION_COLUMNS:
            value, reason = _read(row, col)
            if value is None:
                reasons.append(reason)
                continue
            items += [f"{label}: {s.strip()}" for s in value.split(";") if s.strip()]
        prov = dict(source=[c for c, _ in CONDITION_COLUMNS], method="derived",
                    rule='各栏以 ";" 拆分后加状态前缀合并')
        _put(rec, "applicable_scenario", "; ".join(items) or None,
             reasons[0] if reasons else NullReason.SOURCE_EMPTY, **prov)

    def _fill_citation(self, rec: Record, row: dict, name: str) -> None:
        proposed, proposed_reason = _read(row, COL_YEAR_PROPOSED)
        recommended, _ = _read(row, COL_YEAR_RECOMMENDED)
        prov = dict(source=[COL_NAME, COL_YEAR_PROPOSED, COL_YEAR_RECOMMENDED],
                    method="derived",
                    rule='"Thera-SAbDab: {Therapeutic}, INN proposed {Year Proposed}, '
                         'recommended {Year Recommended}."')
        if proposed is None:
            rec.absent("citation", proposed_reason, **prov)
            return
        text = f"Thera-SAbDab: {name}, INN proposed {proposed}"
        # Year Recommended 实测 88.4% 非空；缺时整句去掉该从句，不填 "na" 假装有值。
        if recommended is not None:
            text += f", recommended {recommended}"
        rec.set("citation", text + ".", **prov)

    def _fill_experiment_conditions(self, rec: Record, row: dict, tier: str | None) -> None:
        """Notes + 实际采用的 SI 档位。

        档位必须落在这里：structure_template 只存 "{pdb}:{chains}"，
        不写档位下游就分不清这个模板是 100% 一致还是 95% 近似。见 Part 4。
        Notes 原样保留 —— 它含序列出处说明（如 "Sequence sourced through DrugBank"），
        是本源序列的二次来源证据，不能丢。
        """
        notes, notes_reason = _read(row, COL_NOTES)
        bits = []
        if tier:
            bits.append(f"structure_template SI: {tier}")
        if notes:
            bits.append(f"Notes: {notes}")
        prov = dict(source=[COL_NOTES, "实际采用的 SI 档位"], method="derived", si_tier=tier)
        _put(rec, "experiment_conditions", "; ".join(bits) or None, notes_reason, **prov)
