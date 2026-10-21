"""SAbDab2 → binder.binder。

规格来源：docs/Mapping/sabdab_to_binder.yaml（唯一来源）。
数据源背景：docs/SourceRegistry/sabdab.yaml。

────────────────────────────────────────────────────────────────────
两条 route，填的字段完全不同，不能互相顶替：

  (a) all_summary —— data/raw/sabdab/<snapshot>/all_summary.csv，实测 21,914 行 × 45 栏。
      填身份 / 靶点 / 结构信息。**45 栏里不含任何氨基酸序列**（v2.0.10 实测）。
  (b) structures —— gucy2c_structures.tgz 里的 mmCIF。
      vh_seq / vl_seq 的唯一来源。summary 里没有，只能从结构档取。

mapping 的 Part 3 `targets` 只描述 route (a)；route (b) 写在 Part 4 的 `structures_route:` 块里。
base.Mapping.targets() 只读顶层 `targets`，看不到 Part 4，
所以 route (b) 的规则由本档自己从 mapping.raw 里取（见 structures_route 属性）。

────────────────────────────────────────────────────────────────────
行粒度：一条 SAbDab2 antibody instance = 一行 = 一条 Record。
  实测 21,914 instances 对应 11,458 个 PDB 条目、6,780 个 SAbDab2 条目
  —— 同一个抗体会出现在多行（不同 PDB、不同分辨率、不同抗原构建体）。
  entity_key = [SABDAB_ID]。**parser 不做去重**：归并是 core.merge_log 的事
  （mapping R1），在 parser 里去重会丢掉「同一抗体的不同观测」这层信息。

本项目靶点在本库的实测覆盖（2026-08-24，全量逐行核对）：
  GUCY2C —— 3 条 instance / 2 个 PDB（8GHO、8GHP）/ 同属 1 个抗体 sabdab2_H03VYL030Q，
             compound 明写 anti-GUCY2C-scFv。
  CDH17  —— 0 条。全库 15 条 cadherin 记录逐条核对为 Cadherin-1 / -3 / -6 与一条
             "Cadherin derived peptide"，没有 Cadherin-17。
             **这是空集，不是检索式写错**（registry 已记：用基因符号检索会得到假空集，
             所以用的是抗原全名 "Cadherin-17" / "LI-cadherin" / "HPT-1"，三条都 0 行）。

不填的字段（勿误用，registry 有明确告警）：
  epitope_position / binding_site —— antigen_chain / antigen_name 只说明「结合了哪条抗原链」，
      不是表位。表位须从 mmCIF 算接触残基后 derived，本轮未做，一律 NOT_MAPPED。
  kd_nm / kon_m1s1 / koff_s1 / measure_* / tm_celsius —— v2.0.10 的 45 栏不含
      affinity / delta_g / affinity_method / temperature / pmid（旧版 SAbDab 有，已移除），
      一律 NOT_MAPPED，须由 DOTAD / 文献源补齐。
  name（抗体名称）—— summary 不提供：compound 是结构标题，SABDAB_ID 是内部 ID。
      按 mapping 走 null，等 Thera-SAbDab / 文献源回填。

assign_uid() / should_include() 不覆写：base 里分别抛 Undecided("Q2") / Undecided("Q4")，
业务侧未定。run() 跑到那里停住是预期行为，不是 bug。
"""
from __future__ import annotations

import csv
import re
import tarfile
from pathlib import Path
from typing import Any, Callable, Iterator

from parsers.base import (
    DATA_ROOT,
    Interim,
    NullReason,
    ParseError,
    Record,
    SourceParser,
    TargetBlock,
)

# 档名。mapping 没有 base 期望的 `source_dataset:` 块（本档 Part 1 只写了取样档路径），
# 所以档名取自 registry 的 下载配置.routes[].output —— 与 downloader 落盘的名字一致。
SUMMARY_CSV = "all_summary.csv"
STRUCTURES_TGZ = "gucy2c_structures.tgz"

ROUTE_SUMMARY = "all_summary"
ROUTE_STRUCTURES = "structures"

#: 源里表示缺失的字面值。实测 45 栏中大量为 "NA"（如 GUCY2C 三行的 heavy_subclass /
#: light_subclass / chainsharing_*）。必须与「真空字符串」分开记，否则填充率会算虚高。
SENTINELS = {"NA"}

#: normalize_antigen_name：构建体后缀，非抗原本名的一部分。
#: 实测 "Guanylyl cyclase C peptide"（8GHO）与 "Guanylyl cyclase C"（8GHP）
#: 是同一个抗原的两种构建体，不归一化会在 target_antigen 上裂成两个靶点。
ANTIGEN_SUFFIXES = (" peptide", " ectodomain", " ecd")

#: derive_binder_format：compound 文本里的显式 format 词 → binder.binder_format 枚举拼写。
#: mapping rule_refs.derive_binder_format 定的优先级是 compound 文本 > type 栏。
FORMAT_WORDS = {"scfv": "scFv", "vhh": "VHH", "fab": "Fab", "igg": "IgG"}
_FORMAT_RE = re.compile(r"(?<![A-Za-z])(scFv|VHH|Fab|IgG)(?![A-Za-z])", re.I)

#: 结构档名两种形态，实测 gucy2c_structures.tgz 内 5 档：
#:   pdb_00008gho_sabdab.cif                整份 PDB 条目
#:   pdb_00008gho_H_L_abag.cif              抗体+抗原裁切档（逐 instance）
_CIF_FULL_RE = re.compile(r"^(?P<pdb>pdb_[0-9a-z]+)_sabdab\.cif$")
_CIF_CROP_RE = re.compile(r"^(?P<pdb>pdb_[0-9a-z]+)_(?P<h>\w+)_(?P<l>\w+)_abag\.cif$")


def clean(raw: Any) -> tuple[str | None, str | None]:
    """→ (值, null 原因)。原因为 None 表示取到了值。

    真空与哨兵 "NA" 都是「数据缺失」，但必须分开记 —— CLAUDE.md 要求区分缺失的种类，
    且朴素非空判断会把 "NA" 当成有值。
    """
    # Missing source cells receive SOURCE_EMPTY rather than a fabricated value.
    if raw is None:
        return None, NullReason.SOURCE_EMPTY
    s = str(raw).strip()
    # Whitespace-only source cells are empty.
    if not s:
        return None, NullReason.SOURCE_EMPTY
    # The explicit NA sentinel remains distinguishable from a truly empty cell.
    if s.upper() in SENTINELS:
        return None, NullReason.SENTINEL_EMPTY
    return s, None


class SabDabParser(SourceParser):
    """SAbDab2 的两条 route。默认跑 summary；structures route 见 build_structure_records()。"""

    mapping_id = "sabdab_to_binder"
    source_dir = "sabdab"

    # Validate the selected route and resolve the snapshot and executable summary mapping.
    def __init__(self, mapping, *, snapshot: str | None = None,
                 route: str = ROUTE_SUMMARY, summary_name: str = SUMMARY_CSV):
        super().__init__(mapping)
        # Stop with a diagnostic: 未知 route：{route}.
        if route not in (ROUTE_SUMMARY, ROUTE_STRUCTURES):
            raise ParseError(f"未知 route：{route}")
        self.route = route
        self.summary_name = summary_name
        self.snapshot_dir = self._resolve_snapshot(snapshot)
        self.block = self._summary_block()

    # ------------------------------------------------------------------
    # 输入定位
    # ------------------------------------------------------------------
    # Use the requested snapshot, otherwise the last lexically sorted snapshot directory.
    def _resolve_snapshot(self, snapshot: str | None) -> Path:
        base = DATA_ROOT / "raw" / self.source_dir
        # An explicit snapshot takes precedence over automatic latest-directory selection.
        if snapshot:
            p = base / snapshot
            # Stop with a diagnostic: 快照目录不存在：{p}.
            if not p.is_dir():
                raise ParseError(f"快照目录不存在：{p}")
            return p
        # Collect items from base.glob('*') only where d.is_dir().
        dirs = sorted(d for d in base.glob("*") if d.is_dir())
        # Stop with a diagnostic: {base} 下没有任何快照目录.
        if not dirs:
            raise ParseError(f"{base} 下没有任何快照目录")
        return dirs[-1]   # 目录名是 YYYYMMDD，字典序即时间序

    def _summary_block(self) -> TargetBlock:
        """Part 3 只有一块 target（binder.binder）。多于一块说明 mapping 变了，显式停。"""
        # Stop with a diagnostic: 预期 Part 3 只有 1 个 target 块，实得 {len(self.targets)}.
        if len(self.targets) != 1:
            raise ParseError(f"预期 Part 3 只有 1 个 target 块，实得 {len(self.targets)}")
        return self.targets[0]

    @property
    def structures_route(self) -> dict:
        """Part 4 的 structures_route 块。

        base.Mapping.targets() 只读顶层 `targets`，而 structures route 是 mapping 里
        第二个独立的 route（record_grain: 一个 mmCIF 结构档），写在顶层 `structures_route:` 下。
        base 看不到它，所以这里直接从 mapping.raw 取 —— 不改 base，也不把它伪装成第二个 target。
        """
        # Use an empty mapping when self.mapping.raw.get('structures_route') is missing or empty.
        return self.mapping.raw.get("structures_route") or {}

    # ------------------------------------------------------------------
    # 读源
    # ------------------------------------------------------------------
    # Choose summary rows or structure-archive member metadata for the selected route.
    def iter_source_rows(self) -> Iterator[dict]:
        # The summary route reads tabular antibody instances.
        if self.route == ROUTE_SUMMARY:
            yield from self.iter_summary_rows()
        # Structure routes iterate downloaded archive files rather than summary CSV rows.
        else:
            yield from self.iter_structure_files()

    def iter_summary_rows(self) -> Iterator[dict]:
        """all_summary.csv 逐行。一行 = 一条 antibody instance，不去重。"""
        path = self.snapshot_dir / self.summary_name
        # Stop with a clear missing-input diagnostic before reading source data.
        if not path.is_file():
            raise ParseError(f"summary 档不存在：{path}")
        # Close the file reliably, including when reading or writing raises an error.
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            # Use an empty list when reader.fieldnames is missing or empty.
            self._check_columns(reader.fieldnames or [], path)
            for i, row in enumerate(reader, start=2):   # 2 = 表头之后第一行
                row["_route"] = ROUTE_SUMMARY
                row["_line"] = i
                yield row

    def iter_structure_files(self) -> Iterator[dict]:
        """结构档打包逐成员。只吐清单，不解出到磁盘 —— 序列抽取见 build_structure_records()。

        实测 gucy2c_structures.tgz：2 个 <pdb>_sabdab.cif + 3 个 <pdb>_<H>_<L>_abag.cif。
        join 回 summary 的键是 PDB（mapping Part 4 join_to_summary.on: PDB），
        裁切档档名里的两条链即 summary 的 Hchain / Lchain。
        """
        path = self.snapshot_dir / STRUCTURES_TGZ
        # Stop with a clear missing-input diagnostic before reading source data.
        if not path.is_file():
            raise ParseError(f"结构档打包不存在：{path}")
        # Close the archive after inspecting its members.
        with tarfile.open(path, "r:gz") as tf:
            # Inspect archive members without extracting arbitrary paths to disk.
            for member in tf.getmembers():
                # Skip archive directories and other non-file members.
                if not member.isfile():
                    continue
                name = Path(member.name).name
                full, crop = _CIF_FULL_RE.match(name), _CIF_CROP_RE.match(name)
                # A full mmCIF filename identifies the PDB but does not identify one chain pair.
                if full:
                    meta = {"kind": "full", "PDB": full["pdb"], "Hchain": None, "Lchain": None}
                # A cropped filename explicitly supplies heavy/light chain labels.
                elif crop:
                    meta = {"kind": "crop", "PDB": crop["pdb"],
                            "Hchain": crop["h"], "Lchain": crop["l"]}
                # Otherwise, stop with a diagnostic: {path.name} 内出现无法识别的档名：{member.name}.
                else:
                    raise ParseError(f"{path.name} 内出现无法识别的档名：{member.name}")
                yield {"_route": ROUTE_STRUCTURES, "_archive": str(path),
                       "_member": member.name, **meta}

    def _check_columns(self, header: list[str], path: Path) -> None:
        """mapping 引用的栏必须真实存在。缺栏 = mapping 与档案脱节，早停好过后面填出空值。"""
        # Collect distinct values from self.block.fields; f.source_columns.
        want = {c for f in self.block.fields for c in f.source_columns}
        missing = sorted(want - set(header))
        # Stop with a diagnostic: {path.name} 缺少 mapping 引用的栏：{', '.join(missing)}.
        if missing:
            raise ParseError(f"{path.name} 缺少 mapping 引用的栏：{', '.join(missing)}")

    # ------------------------------------------------------------------
    # 建记录
    # ------------------------------------------------------------------
    # Dispatch source rows to summary mapping or the explicitly unimplemented structure handler.
    def build_records(self, row: dict, out: Interim) -> Iterator[Record]:
        # Structure metadata goes to the deliberately unimplemented sequence-extraction handler.
        if row.get("_route") == ROUTE_STRUCTURES:
            yield from self.build_structure_records(row, out)
            return
        yield from self.build_summary_records(row, out)

    def build_summary_records(self, row: dict, out: Interim) -> Iterator[Record]:
        """一行 instance → 一条 Record（record_per_source: one）。"""
        # Build mapped values from self.block.entity_key.
        rec = Record(
            table=self.block.table,
            entity_key={k: (row.get(k) or None) for k in self.block.entity_key},
        )
        # Execute the mapping rule for each target field.
        for rule in self.block.fields:
            # A constant rule obtains its value from the mapping, not the source row.
            if rule.method == "constant":
                if rule.value is None:
                    # mapping 显式写 value: null（contrary_evidence）—— 本源结构上就没有这种标记。
                    rec.absent(rule.target, NullReason.NOT_MAPPED,
                               method="constant", note=rule.note)
                # Otherwise, store the mapped value with its provenance.
                else:
                    rec.set(rule.target, rule.value, method="constant")
            # A direct rule preserves the declared source cell and its missing-value reason.
            elif rule.method == "direct":
                col = rule.source_columns[0]
                val, reason = clean(row.get(col))
                # Empty/sentinel source values are recorded as absent with provenance.
                if reason:
                    rec.absent(rule.target, reason, source=col, method="direct")
                # Otherwise, store the mapped value with its provenance.
                else:
                    rec.set(rule.target, val, source=col, method="direct")
            # Derived fields dispatch to explicit handlers rather than evaluating prose rules.
            elif rule.method == "derived":
                handler = self._DERIVED.get(rule.target)
                # Stop with a diagnostic: mapping 的 {rule.target} 是 derived，但 parser 没有对应实现.
                if handler is None:
                    raise ParseError(
                        f"mapping 的 {rule.target} 是 derived，但 parser 没有对应实现"
                    )
                handler(self, row, rule, rec)
            # Otherwise, stop with a diagnostic: 未知 method：{rule.method}（target={rule.target}）.
            else:
                raise ParseError(f"未知 method：{rule.method}（target={rule.target}）")

        # Collect items from self.block.fields only where r.required and rec.values.get(r.target) is
        # None.
        missing_required = [
            r.target for r in self.block.fields
            if r.required and rec.values.get(r.target) is None
        ]
        # Reject a record if a mapping-required field could not be produced.
        if missing_required:
            out.reject("required_missing", line=row.get("_line"),
                       entity_key=rec.entity_key, columns=missing_required)
            return
        yield rec

    def build_structure_records(self, row: dict, out: Interim) -> Iterator[Record]:
        """mmCIF → vh_seq / vl_seq。**未实现，故意留桩。**

        为什么不顺手写：实测这 5 个档后，有三处需要先定案，任何一处猜错都会往 A 库里
        灌进「看着像序列、其实不是那条序列」的值 —— 错的序列比没有序列糟得多。

        (1) 解析器选型。这 5 个档是 SAbDab2 重排过的 mmCIF：_entity_poly 是 4 栏 loop_，
            pdbx_seq_one_letter_code 整条挤在一行、不加引号（实测 8GHO H 链 121 aa 单行）。
            而 RCSB 官方 mmCIF 把该栏写成 `;` 包围的多行文本块。
            手写按行切的解析器在这 5 个档上能过，在 all-structures 全量上会静默错位。
            => 要么固定用 gemmi / Biopython MMCIF2Dict，要么明确「只吃 SAbDab2 重排格式」
               并在读到 `;` 块时显式报错。这是选型决策，不该由 parser 私自定。

        (2) 取哪一段。pdbx_seq_one_letter_code 是**构建体全长**，不是可变域：
            实测 8GHO 的 L 链尾部带 TEV 位点 …TGSENLYFQ，头部多出 SG；
            8GHP 的 entity 1 是抗原（GUCY2C ECD，417 aa）尾部同样带 GGGGSENLYFQ。
            直接塞进 vl_seq 等于把带标签的构建体标成可变域。
            裁到 VH/VL 边界需要抗体编号（ANARCI/IMGT），而 mapping 把 numbering 列为
            not_available 并明令「不得写死 constant IMGT」—— 编号方案本身是未决项。
            => 先定「vh_seq/vl_seq 存构建体全长还是可变域」，再谈实现。

        (3) 链 → entity 的对应。整份档（<pdb>_sabdab.cif）的 pdbx_strand_id 是逗号串
            （实测 8GHO：entity 1 = "A,H"），而裁切档里同一条链单独成 entity。
            summary 的 8GHO 有 A-B 与 H-L 两条 instance，指向同一对序列。
            用哪个档为准（整份 vs 裁切）、以及非标准残基在非 can 栏里写作 "(MSE)" 时怎么处理
            （这 5 个档没有 _can 栏），都要先定。

        另：mapping Part 4 还要求本 route 用 mmCIF citation 块（含 DOI / PubMed ID）
        覆盖 summary 组出来的 citation。覆盖发生在归并阶段还是 parser 内，也未定。
        """
        raise NotImplementedError(
            "structures route（vh_seq / vl_seq）未实现。需先定案：\n"
            "  (1) mmCIF 解析器选型（gemmi / Biopython MMCIF2Dict vs 自写行解析）——\n"
            "      SAbDab2 重排档把序列写成单行不加引号，RCSB 原档写成 `;` 多行块，两者不通用；\n"
            "  (2) vh_seq/vl_seq 的定义：_entity_poly.pdbx_seq_one_letter_code 是带标签的构建体全长\n"
            "      （实测 8GHO L 链尾部有 TEV 位点 TGSENLYFQ），裁到可变域需抗体编号，\n"
            "      而 numbering 在 mapping 里是 not_available 且不得写死 IMGT；\n"
            "  (3) 链→entity 对应以整份档（pdbx_strand_id 为 'A,H' 逗号串）还是裁切档为准，\n"
            "      以及非标准残基 (XXX) 的处理。\n"
            f"  本次待处理成员：{row.get('_member')}"
        )

    # ------------------------------------------------------------------
    # derived 规则（Part 3 的 rule / rule_ref 逐条实现）
    # ------------------------------------------------------------------
    def _d_citation(self, row: dict, rule, rec: Record) -> None:
        """'{authors} ({date:%Y}). {compound}. PDB {PDB}.'；缺的部分省略，全缺则 null。"""
        authors, _ = clean(row.get("authors"))
        compound, _ = clean(row.get("compound"))
        pdb, _ = clean(row.get("PDB"))
        raw_date, _ = clean(row.get("date"))
        # Use raw_date.split('/')[0] when raw date is truthy; otherwise use None.
        year = raw_date.split("/")[0] if raw_date else None
        # Discard an invalid year rather than guessing how to repair its date.
        if year and not re.fullmatch(r"\d{4}", year):
            year = None            # 源格式实测 YYYY/MM/DD；不合就不猜
        parts = []
        # Include reported authors and the year when available.
        if authors:
            # Use f'{authors} ({year}).' when year is truthy; otherwise use f'{authors}.'.
            parts.append(f"{authors} ({year})." if year else f"{authors}.")
        # A known year is still useful when the author field is missing.
        elif year:
            parts.append(f"({year}).")
        # Include a reported compound description in the citation.
        if compound:
            parts.append(f"{compound}.")
        # Keep the original PDB spelling in the source citation.
        if pdb:
            parts.append(f"PDB {pdb}.")   # 保留源写法 pdb_00008gho，不自行改写成 8GHO
        # A citation with no reported components remains absent.
        if not parts:
            rec.absent(rule.target, NullReason.SOURCE_EMPTY, source=rule.source_columns)
            return
        rec.set(rule.target, " ".join(parts), source=rule.source_columns,
                method="derived", rule=rule.rule)

    def _d_experiment_conditions(self, row: dict, rule, rec: Record) -> None:
        """'{method}, {resolution} Å, Rfree {r_free}, Rfactor {r_factor}'；NA 项省略。"""
        method, _ = clean(row.get("method"))
        res, _ = clean(row.get("resolution"))
        rfree, _ = clean(row.get("r_free"))
        rfac, _ = clean(row.get("r_factor"))
        # Collect items from the declared input collections only where p.
        parts = [p for p in (method,
                             f"{res} Å" if res else None,
                             f"Rfree {rfree}" if rfree else None,
                             f"Rfactor {rfac}" if rfac else None) if p]
        # No structural-method components means experimental conditions remain unknown.
        if not parts:
            rec.absent(rule.target, NullReason.SOURCE_EMPTY, source=rule.source_columns)
            return
        rec.set(rule.target, ", ".join(parts), source=rule.source_columns,
                method="derived", rule=rule.rule)

    def _d_target_antigen(self, row: dict, rule, rec: Record) -> None:
        """rule_ref: normalize_antigen_name —— 去构建体后缀，保留抗原本名。"""
        val, reason = clean(row.get("antigen_name"))
        # An absent antigen label cannot be normalized into a target name.
        if reason:
            rec.absent(rule.target, reason, source="antigen_name",
                       rule_ref=rule.rule_ref)
            return
        name = val
        changed = True
        while changed:                      # "X peptide ECD" 这类叠加后缀
            changed = False
            # Check only the explicitly allowed construct suffixes.
            for suf in ANTIGEN_SUFFIXES:
                # Remove a matching suffix, then repeat in case suffixes are stacked.
                if name.lower().endswith(suf):
                    name, changed = name[: -len(suf)].strip(), True
        if not name:                        # 整条只剩后缀，说明规则不适用于这一行
            rec.absent(rule.target, NullReason.DERIVATION_FAILED,
                       source="antigen_name", raw=val, rule_ref=rule.rule_ref)
            return
        rec.set(rule.target, name, source="antigen_name", method="derived",
                rule_ref=rule.rule_ref, raw=val)

    def _d_epitope_kind(self, row: dict, rule, rec: Record) -> None:
        """antigen_type → 线性/构象/未知。

        【R2】这是本档唯一「推断而非实测」的字段：antigen_type 说的是「抗原是肽还是蛋白」，
        不等于「表位是线性还是构象」。若引用可追溯性检查要求每个值都有原文出处，
        此栏应整栏改填 未知 —— 改法是改 mapping 的 value_map，不是改这里。
        """
        # Build mapped values from (rule.extra.get('value_map') or {}).items().
        vmap = {str(k).upper(): v for k, v in (rule.extra.get("value_map") or {}).items()}
        # Use empty text when row.get('antigen_type') is missing or empty.
        raw = (row.get("antigen_type") or "").strip()
        val = vmap.get(raw.upper())
        # An antigen type outside the explicit value map cannot produce an inferred epitope kind.
        if val is None:
            rec.absent(rule.target, NullReason.DERIVATION_FAILED,
                       source="antigen_type", raw=raw,
                       note="value_map 里没有这个取值")
            return
        rec.set(rule.target, val, source="antigen_type", method="derived",
                raw=raw, note="推断值，非实测表位类型")

    def _d_complex_structure(self, row: dict, rule, rec: Record) -> None:
        """antigen_chain 非 NA 时填 '{PDB}:{antigen_chain}'，否则 null。

        注意：这只是「本结构里抗原是哪条链」，**不是表位**。
        epitope_position / binding_site 一律不由此栏推，见档头。
        """
        pdb, pdb_reason = clean(row.get("PDB"))
        chain, chain_reason = clean(row.get("antigen_chain"))
        if chain_reason:                    # 实测 NA 表示该 instance 无抗原（全库 21,914 中 19,560 有抗原）
            rec.absent(rule.target, chain_reason, source=rule.source_columns)
            return
        # A missing PDB identifier prevents a compound structure reference.
        if pdb_reason:
            rec.absent(rule.target, pdb_reason, source=rule.source_columns)
            return
        rec.set(rule.target, f"{pdb}:{chain}", source=rule.source_columns,
                method="derived", rule=rule.rule)

    def _d_germline(self, row: dict, rule, rec: Record) -> None:
        """heavy_species / light_species：相同取其一，不同填 'H:x/L:y'。

        只记来源物种。**不得据此填 humanization** —— 物种 ≠ 人源化程度（mapping Part 1）。
        """
        h, h_reason = clean(row.get("heavy_species"))
        l, l_reason = clean(row.get("light_species"))
        # When both chain species are known, retain agreement or explicitly label the difference.
        if h and l:
            # Use h when h equals l; otherwise use f'H:{h}/L:{l}'.
            val = h if h == l else f"H:{h}/L:{l}"
        # With only one species, label its chain rather than implying both chains share it.
        elif h or l:
            # Use f'H:{h}' when h is truthy; otherwise use f'L:{l}'.
            val = f"H:{h}" if h else f"L:{l}"
        # Otherwise, record null together with its source/derivation reason.
        else:
            # Prefer h_reason; if empty or absent, fall back to l_reason.
            rec.absent(rule.target, h_reason or l_reason, source=rule.source_columns)
            return
        rec.set(rule.target, val, source=rule.source_columns, method="derived",
                rule=rule.rule)

    def _d_species_reactivity(self, row: dict, rule, rec: Record) -> None:
        """antigen_species。单点观察（本结构里结合的抗原来自哪个物种），非跨物种反应性谱。"""
        val, reason = clean(row.get("antigen_species"))
        # Unreported antigen species cannot establish species reactivity.
        if reason:
            rec.absent(rule.target, reason, source="antigen_species")
            return
        rec.set(rule.target, val, source="antigen_species", method="derived",
                note="单点观察，非反应性谱")

    def _d_format(self, row: dict, rule, rec: Record) -> None:
        """rule_ref: derive_binder_format —— compound 文本里的显式 format 词 > type 栏。

        实测 8GHO/8GHP 的 type 全是 "FV"（value_map 落到 其他），
        而 compound 写明 "anti-GUCY2C-scFv antibody" —— 只看 type 会把这个 scFv 判成 其他。
        """
        compound, _ = clean(row.get("compound"))
        # Prefer a format explicitly stated in the compound description.
        if compound:
            m = _FORMAT_RE.search(compound)
            # Use the matched format keyword before consulting the less-specific type column.
            if m:
                rec.set(rule.target, FORMAT_WORDS[m.group(1).lower()],
                        source="compound", method="derived", rule_ref=rule.rule_ref,
                        raw=m.group(0), note="由 compound 文本判定，优先于 type 栏")
                return
        # Build mapped values from (rule.extra.get('value_map') or {}).items().
        vmap = {str(k).upper(): v for k, v in (rule.extra.get("value_map") or {}).items()}
        # Use empty text when row.get('type') is missing or empty.
        raw_type = (row.get("type") or "").strip()
        val = vmap.get(raw_type.upper())
        # Unmapped types receive the mapping's declared Other fallback.
        if val is None:
            val = "其他"                     # rule_refs.derive_binder_format.fallback
            note = "type 不在 value_map 内，按 mapping 的 fallback 落 其他"
        # A recognized source type records the direct mapping explanation.
        else:
            note = "由 type 栏判定"
        rec.set(rule.target, val, source=rule.source_columns, method="derived",
                rule_ref=rule.rule_ref, raw=raw_type, note=note)

    #: derived target → 实现。mapping 长出新的 derived 字段而这里没有对应实现时，
    #: build_summary_records() 会显式报错，而不是静默少填一栏。
    _DERIVED: dict[str, Callable[..., None]] = {
        "citation": _d_citation,
        "experiment_conditions": _d_experiment_conditions,
        "target_antigen": _d_target_antigen,
        "epitope_kind": _d_epitope_kind,
        "complex_structure": _d_complex_structure,
        "germline": _d_germline,
        "species_reactivity": _d_species_reactivity,
        "format": _d_format,
    }

    # ------------------------------------------------------------------
    # null 原因
    # ------------------------------------------------------------------
    def fill_absent(self, rec: Record) -> None:
        """补 base 补不到的那部分。

        base.fill_absent() 读的是 unmapped_target_columns.not_available，
        而本档 mapping 把填不了的列拆成了三块：
            not_available_in_all_summary / not_available_at_all / epitope_gap.columns
        —— 键名不同，base 那句取不到任何列（实测返回空表）。
        不在这里补上的话，「本源没这个字段」与「这一行恰好空」在 interim 里就分不开了。
        （这是 mapping 与 base 的键名脱节，如实记录，不改 mapping 也不改 base。）
        """
        super().fill_absent(rec)            # platform_managed 那块键名一致，base 能读到
        # Add this source's missing-field reasons without overwriting existing audit explanations.
        for col in self._absent_columns():
            rec.null_reasons.setdefault(col, NullReason.NOT_MAPPED)

    # Collect unmapped columns, adding summary-only gaps only for the summary route.
    def _absent_columns(self) -> list[str]:
        # Use an empty mapping when self.mapping.raw.get('unmapped_target_columns') is missing or
        # empty.
        um = self.mapping.raw.get("unmapped_target_columns") or {}
        # Use an empty list when um.get('not_available_at_all') is missing or empty.
        cols = list(um.get("not_available_at_all") or [])
        # Apply the explicit fallbacks to missing/empty values while retaining any reported nonempty
        # values.
        cols += list((um.get("epitope_gap") or {}).get("columns") or [])
        if self.route == ROUTE_SUMMARY:
            # 序列三栏只在 summary route 缺；structures route 落地后这里不该再声明缺失。
            cols += list(um.get("not_available_in_all_summary") or [])
        return cols
