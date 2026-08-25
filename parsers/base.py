"""Parser 公共契约。

parser 的定义（业务侧 2026-08-24 确认）：
    输入 raw data + mapping doc + schema，输出 normalised data ready to enter the db。

所以 parser 只做「按映射规则把源记录变成库记录」这一件事：
不取数（那是 downloaders/），不写库（那是后续 loader）。

三段流水线彼此同构，各自可独立重跑：
    downloader:  URL                    → data/raw/…      不解析
    parser:      raw + mapping + schema → data/interim/…  不写库
    loader:      interim                → PostgreSQL      不做映射

可执行内容的唯一来源是 docs/Mapping/*.yaml。
mapping 的散文部分（note / risks / source_field_inventory 的说明）是给人看的，
代码只读 Part 3「可执行映射」的 targets 块与 Part 4 的 rule_refs。

────────────────────────────────────────────────────────────────────
本文件是骨架。已定的部分可运行；未决的部分显式抛 Undecided 而不是猜。
未决清单见下方 OPEN_QUESTIONS。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAPPING_DIR = ROOT / "docs" / "Mapping"
DATA_ROOT = Path(os.environ.get("CART_DATA_ROOT") or (ROOT / "data"))

PARSER_VERSION = "0.1.0"


class ParseError(RuntimeError):
    """解析失败，且不该靠重试解决。"""


# --------------------------------------------------------------------------
# 未决问题
# --------------------------------------------------------------------------
# 2026-08-24 与业务侧确认：这些要先跟团队对齐再落。骨架跑到这里必须停，
# 不能猜一个答案继续 —— CLAUDE.md：「一个听起来合理的编造细节，
# 比一个被标记出来的缺口更糟」。
OPEN_QUESTIONS: dict[str, str] = {
    "Q1": (
        "binder.binder 一行是「一个 binder」还是「一次观测」？\n"
        "  docs/Schema/Schema_A.yaml 是两表（binder 20 字段 + binder_evidence 26 字段，1:N），\n"
        "  sql/03_binder.sql 压成了单表。三份 mapping 都 target 单表，\n"
        "  且 dotad_to_binder.yaml 有 record_per_source: many —— 指向「一行=一次观测」。\n"
        "  影响：parser 输出是一股流还是两股流。"
    ),
    "Q2": (
        "uid 需要跨重跑稳定吗？\n"
        "  entity_key 在同一 binder 的多次观测间相同，uid 是 PRIMARY KEY 必须唯一。\n"
        "  依赖行号 → 上游行序一变，merged_into / core.evidence.entity_uid 集体错位。\n"
        "  内容 hash → 稳定，但要先定死「哪些字段进 hash」。"
    ),
    "Q3": (
        "跨源实体归一化用的别名表，算不算 parser 的输出？\n"
        "  Thera-SAbDab 的 Alternative Therapeutic Names（1,032 唯一值，99.7% 填充）\n"
        "  被 mapping 标为 target: null /「不直接入库，但必须交给实体归一化用」。\n"
        "  不作为 parser 输出 → 归并阶段得自己回 data/raw/ 捞，绕过 mapping 层。"
    ),
    "Q4": (
        "入库范围：全量还是只要 GCC/CDH17？\n"
        "  「binder 数据库要 GCC/CDH17 相关」当时说的是下载范围，入库范围未定。\n"
        "  实测 GUCY2C 在 SAbDab 只有 1 个抗体、CDH17 为 0，只入靶点相关＝库里个位数条。"
    ),
}


class Undecided(NotImplementedError):
    """未决问题的统一出口。

    带上问题编号与全文，让骨架停在哪、为什么停、停的是哪个决策一目了然。
    """

    def __init__(self, qid: str, hint: str = ""):
        self.qid = qid
        body = OPEN_QUESTIONS.get(qid, "（未登记的问题）")
        msg = f"[{qid}] 未决，骨架在此停止。\n{body}"
        if hint:
            msg += f"\n  落点：{hint}"
        super().__init__(msg)


# --------------------------------------------------------------------------
# null 原因词表
# --------------------------------------------------------------------------
# CLAUDE.md 硬要求：「数据缺失」必须区别于「抽取失败」。
# 库里一个字段是 null 看不出是哪种，所以原因记在 interim 层，逐字段。
class NullReason:
    NOT_MAPPED = "not_mapped"              # 本源结构上就没这个字段（mapping 的 not_available）
    PLATFORM_MANAGED = "platform_managed"  # 由平台生成（uid / version / batch_id …）
    SOURCE_EMPTY = "source_empty"          # 源里有这栏，但这一行是空 —— 数据缺失
    SENTINEL_EMPTY = "sentinel_empty"      # 源里写的是 "None" / "na" 这类哨兵 —— 也是缺失，
                                           # 但必须与真空区分：朴素非空判断会把填充率算虚高
                                           # （thera_sabdab R4：99%/95-98% SI Structure 含 "None;None"）
    DERIVATION_FAILED = "derivation_failed"  # 派生规则跑了但失败 —— 抽取失败
    VALIDATION_FAILED = "validation_failed"  # 取到值了但不合 schema —— 抽取失败

    ABSENT = frozenset({NOT_MAPPED, PLATFORM_MANAGED, SOURCE_EMPTY, SENTINEL_EMPTY})
    FAILED = frozenset({DERIVATION_FAILED, VALIDATION_FAILED})


# --------------------------------------------------------------------------
# Mapping doc
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldRule:
    """Part 3 targets[].fields[] 的一条。"""

    target: str
    source: Any = None          # str | list[str] | None
    method: str = "direct"      # direct / derived / constant
    value: Any = None           # method=constant 时的字面值
    rule_ref: str | None = None
    rule: str | None = None     # 散文规则；无 rule_ref 时由源 parser 自行实现
    required: bool = False
    note: str | None = None
    #: mapping 里出现、但 base 尚未认识的键（如 dotad 的 unit_from）。
    #: 不认识就收进来交给源 parser，不要因为 mapping 多写一个键就整份加载失败 ——
    #: mapping 是文档层，会先于代码层长出新键，这是常态不是错误。
    extra: dict = field(default_factory=dict)

    @classmethod
    def of(cls, spec: dict) -> "FieldRule":
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        return cls(**{k: v for k, v in spec.items() if k in known},
                   extra={k: v for k, v in spec.items() if k not in known})

    @property
    def source_columns(self) -> list[str]:
        if self.source is None:
            return []
        return list(self.source) if isinstance(self.source, list) else [self.source]


@dataclass(frozen=True)
class TargetBlock:
    """Part 3 targets[] 的一块 —— 一种产出记录的方式。"""

    table: str
    fields: list[FieldRule]
    record_per_source: str = "one"   # one / many
    condition: str | None = None
    entity_key: list[str] = field(default_factory=list)
    iterate_over: str | None = None
    note: str | None = None

    @property
    def db_name(self) -> str:
        """"binder.binder" → "binder"。interim 目录按库分层用。"""
        return self.table.split(".")[0]


@dataclass(frozen=True)
class Mapping:
    path: Path
    raw: dict

    @property
    def mapping_id(self) -> str:
        return self.raw.get("mapping_id") or self.path.stem

    @property
    def source_name(self) -> str:
        return self.raw["source_name"]

    @property
    def route_id(self) -> str | None:
        return self.raw.get("route_id")

    @property
    def status(self) -> str:
        return self.raw.get("status", "unknown")

    @property
    def record_grain(self) -> str:
        return (self.raw.get("record_grain") or "").strip()

    @property
    def target_schema(self) -> str:
        """如 "sql/03_binder.sql → binder.binder"。

        这一行是 parser 输出词表的来源。docs/Schema/Schema_A.yaml 与 sql/03_binder.sql
        字段命名不同（vh_sequence vs vh_seq，两表 vs 单表），孰为准尚未定。
        base.py 对此保持中立：mapping 指哪就用哪，不在代码里写死任何一套。
        """
        v = self.raw.get("target_schema")
        if not v:
            raise ParseError(f"{self.path.name} 缺少 target_schema —— parser 不知道该产出什么词表")
        return v

    @property
    def schema_path(self) -> Path:
        """从 target_schema 里取出档案路径部分。"""
        head = self.target_schema.split("→")[0].split("->")[0].strip()
        p = ROOT / head
        if not p.is_file():
            raise ParseError(f"{self.path.name} 的 target_schema 指向 {p}，该档不存在")
        return p

    @property
    def source_datasets(self) -> list[tuple[str, dict]]:
        """输入档声明，一律归一成 [(名字, spec)]。

        三份 mapping 用了三种写法，2026-08-24 实测：
          thera_sabdab  source_dataset  单数，一个 dict
          dotad         source_datasets 复数，dict-of-dicts（metadata / sequences / …）
          sabdab        两者都没有，只在 Part 1 的注释里写了档路径
        base 不强求文档层统一措辞 —— 能认的都认，认不到就交回空表，
        由 run() 在清单里显式标注「未登记 raw 输入」，而不是假装链条完整。
        """
        ds = self.raw.get("source_datasets") or self.raw.get("source_dataset")
        if not ds:
            return []
        if isinstance(ds, list):
            return [(str(d.get("name") or i), d) for i, d in enumerate(ds)]
        if all(isinstance(v, dict) for v in ds.values()):
            return list(ds.items())          # 复数：dict-of-dicts
        return [("source_dataset", ds)]      # 单数：本身就是那个 spec

    @property
    def source_dataset(self) -> dict:
        ds = self.raw.get("source_dataset")
        if not ds:
            raise ParseError(f"{self.path.name} 缺少 source_dataset —— 不知道读哪个 raw 档")
        return ds

    @property
    def rule_refs(self) -> dict:
        return self.raw.get("rule_refs") or {}

    @property
    def not_available(self) -> list[str]:
        """本源填不了的库字段。用来给 null_reason 定 NOT_MAPPED。"""
        return (self.raw.get("unmapped_target_columns") or {}).get("not_available") or []

    @property
    def platform_managed(self) -> list[str]:
        return (self.raw.get("unmapped_target_columns") or {}).get("platform_managed") or []

    def targets(self) -> list[TargetBlock]:
        blocks = self.raw.get("targets")
        if not blocks:
            raise ParseError(f"{self.path.name} 没有 Part 3 targets 块，无法驱动 parser")
        out = []
        for b in blocks:
            out.append(
                TargetBlock(
                    table=b["table"],
                    record_per_source=b.get("record_per_source", "one"),
                    condition=b.get("condition"),
                    entity_key=list(b.get("entity_key") or []),
                    iterate_over=b.get("iterate_over"),
                    note=b.get("note"),
                    fields=[FieldRule.of(f) for f in (b.get("fields") or [])],
                )
            )
        return out


def load_mapping(name_or_path: str) -> Mapping:
    """接受 `thera_sabdab_to_binder`、`….yaml` 或完整路径。"""
    cand = Path(name_or_path)
    if not cand.is_file():
        cand = MAPPING_DIR / f"{cand.stem or name_or_path}.yaml"
    if not cand.is_file():
        raise ParseError(f"找不到 mapping：{name_or_path}（查过 {cand}）")
    with cand.open(encoding="utf-8") as fh:
        return Mapping(path=cand, raw=yaml.safe_load(fh))


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Column:
    name: str
    type: str
    not_null: bool = False
    generated: bool = False   # GENERATED ALWAYS / DEFAULT —— 不由 parser 提供


_CONSTRAINT_HEAD = re.compile(
    r"^\s*(CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|EXCLUDE)\b", re.I
)


def _split_top_level(body: str) -> Iterator[str]:
    """按顶层逗号切分。numeric(3,2) 与 GENERATED ALWAYS AS (…) 里的逗号不能切。"""
    depth, buf = 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            yield "".join(buf)
            buf = []
        else:
            buf.append(ch)
    if buf:
        yield "".join(buf)


@dataclass(frozen=True)
class Schema:
    """目标库的列定义。来源可以是 SQL DDL 或 Schema_*.yaml —— 由 mapping 指定。"""

    origin: Path
    table: str
    columns: dict[str, Column]

    @classmethod
    def from_sql(cls, path: Path, table: str) -> "Schema":
        text = path.read_text(encoding="utf-8")
        m = re.search(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + re.escape(table) + r"\s*\(",
            text, re.I,
        )
        if not m:
            raise ParseError(f"{path.name} 里找不到 CREATE TABLE {table}")
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += (text[i] == "(") - (text[i] == ")")
            i += 1
        body = re.sub(r"--[^\n]*", "", text[m.end():i - 1])   # 去行内注释
        cols: dict[str, Column] = {}
        for frag in _split_top_level(body):
            frag = frag.strip()
            if not frag or _CONSTRAINT_HEAD.match(frag):
                continue
            parts = frag.split(None, 1)
            if len(parts) < 2:
                continue
            name, rest = parts[0], parts[1]
            cols[name] = Column(
                name=name,
                type=rest.split()[0],
                not_null=bool(re.search(r"\bNOT\s+NULL\b", rest, re.I)),
                generated=bool(re.search(r"\bGENERATED\b|\bDEFAULT\b", rest, re.I)),
            )
        return cls(origin=path, table=table, columns=cols)

    @classmethod
    def from_yaml(cls, path: Path, table: str) -> "Schema":
        """Schema_A.yaml 形态：顶层块 → {table, fields: {name: {type, nullable}}}。"""
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        want = table.split(".")[-1]
        block = next(
            (v for v in doc.values()
             if isinstance(v, dict) and v.get("table") == want),
            None,
        )
        if block is None:
            raise ParseError(f"{path.name} 里找不到 table={table}")
        cols = {
            name: Column(
                name=name,
                type=str(spec.get("type", "")),
                not_null=spec.get("nullable") is False,
                generated=False,
            )
            for name, spec in (block.get("fields") or {}).items()
        }
        return cls(origin=path, table=table, columns=cols)

    @classmethod
    def for_mapping(cls, mapping: Mapping, table: str) -> "Schema":
        p = mapping.schema_path
        return cls.from_sql(p, table) if p.suffix == ".sql" else cls.from_yaml(p, table)

    def unknown(self, names) -> list[str]:
        """mapping 写了、schema 里没有的列 —— mapping 与 schema 脱节的早期信号。"""
        return sorted(n for n in names if n not in self.columns)

    def missing_required(self, values: dict) -> list[str]:
        return sorted(
            c.name for c in self.columns.values()
            if c.not_null and not c.generated and values.get(c.name) is None
        )


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
@dataclass
class Record:
    """一条待入库记录 + 它的逐字段来历。

    provenance 不进 core.evidence —— 业务侧 2026-08-24 定：core.evidence 只服务
    lit / patent 两类 doc_kind，数据库源不进那张表。所以数据库源的逐字段溯源
    只活在 interim 层，这是这一层存在的主要理由之一。
    """

    table: str
    entity_key: dict[str, Any]
    values: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, dict] = field(default_factory=dict)
    null_reasons: dict[str, str] = field(default_factory=dict)
    uid: str | None = None

    def set(self, column: str, value: Any, **prov) -> None:
        self.values[column] = value
        if prov:
            self.provenance[column] = prov

    def absent(self, column: str, reason: str, **prov) -> None:
        self.values[column] = None
        self.null_reasons[column] = reason
        if prov:
            self.provenance[column] = prov


def content_uid(*parts: Any) -> str:
    """内容 hash。Q2 若定为「uid 必须跨重跑稳定」，用这个而不是行号。

    只是工具，不代表 Q2 已定 —— 调用点仍应先过 Undecided("Q2")。
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:32]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(1 << 20):
            h.update(block)
    return h.hexdigest()


class Interim:
    """data/interim/<db>/<source_dir>/<parse_date>/ 这一层，外加 _manifest.json。

    目录名用「解析日期」，不是原始快照日期 —— 同一份 raw 快照会被不同版本的
    mapping 反复解析，两个日期必须能分开。消费掉的 raw 快照记在 manifest 的 inputs 里。

    落三个档：
        records.jsonl   每行一条待入库记录 + 逐字段 provenance + null_reasons
        rejects.jsonl   没能产出记录的源行 + 原因（绝不静默丢）
        _manifest.json  输入档与 sha256、mapping 档与 sha256、parser 版本、计数
    """

    RECORDS = "records.jsonl"
    REJECTS = "rejects.jsonl"
    MANIFEST = "_manifest.json"

    def __init__(self, db: str, source_dir: str, parse_date: str | None = None):
        self.db = db
        self.source_dir = source_dir
        self.parse_date = parse_date or date.today().strftime("%Y%m%d")
        self.dir = DATA_ROOT / "interim" / db / source_dir / self.parse_date
        self.dir.mkdir(parents=True, exist_ok=True)
        self.n_records = 0
        self.n_rejects = 0
        self.inputs: list[dict] = []
        self._rec_fh = None
        self._rej_fh = None

    # --- 输入登记：证据链上「这批数据由哪份 raw + 哪份 mapping 产出」那一环 ---
    def consume(self, path: Path, kind: str, note: str | None = None) -> None:
        if not path.is_file():
            raise ParseError(f"输入档不存在：{path}")
        self.inputs.append({
            "kind": kind,                     # raw / mapping / schema
            "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
            "note": note,
        })

    def __enter__(self) -> "Interim":
        self._rec_fh = (self.dir / self.RECORDS).open("w", encoding="utf-8")
        self._rej_fh = (self.dir / self.REJECTS).open("w", encoding="utf-8")
        return self

    def __exit__(self, *exc) -> None:
        for fh in (self._rec_fh, self._rej_fh):
            if fh:
                fh.close()

    def emit(self, rec: Record) -> None:
        self._rec_fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        self.n_records += 1

    def reject(self, reason: str, **info) -> None:
        """源行没能变成记录。reason 用 NullReason.FAILED 里的词，或自定义的失败类型。"""
        self._rej_fh.write(json.dumps({"reason": reason, **info}, ensure_ascii=False) + "\n")
        self.n_rejects += 1

    def finish(self, *, mapping: Mapping, extra: dict | None = None) -> Path:
        n_raw = sum(1 for i in self.inputs if i["kind"] == "raw")
        warning = None if n_raw else (
            "本批未登记任何 raw 输入档 —— 证据链在「由哪份原始快照产出」这一环是断的。"
            "多半是 mapping 缺 source_dataset(s) 块，或 parser 未覆写 source_paths()。"
        )
        manifest = {
            "db": self.db,
            "source_name": mapping.source_name,
            "mapping_id": mapping.mapping_id,
            "mapping_status": mapping.status,
            "target_schema": mapping.target_schema,
            "record_grain": mapping.record_grain,
            "parse_date": self.parse_date,
            "parser_version": PARSER_VERSION,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "record_count": self.n_records,
            "reject_count": self.n_rejects,
            "raw_input_count": n_raw,
            "warning": warning,
            "inputs": self.inputs,
            **(extra or {}),
        }
        p = self.dir / self.MANIFEST
        with p.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        return p


# --------------------------------------------------------------------------
# 源 parser 的接口
# --------------------------------------------------------------------------
class SourceParser:
    """每个结构化源实现一个子类。

    子类只负责「怎么把这个源的一行读成 Record」；
    加载 mapping / 校验 schema / 落盘 / 写清单 都在 base 这边，不要重复实现。
    """

    #: 对应 docs/Mapping/ 下的档名（不含 .yaml）
    mapping_id: str = ""
    #: data/interim/<db>/<source_dir>/ 里的 <source_dir>，与 data/raw/ 下的目录名一致
    source_dir: str = ""

    def __init__(self, mapping: Mapping):
        self.mapping = mapping
        self.targets = mapping.targets()
        self.schemas = {t.table: Schema.for_mapping(mapping, t.table) for t in self.targets}

    # --- 子类必须实现 ---
    def iter_source_rows(self) -> Iterator[dict]:
        """按 mapping.source_dataset 读 raw 档，逐行吐出源记录（原始栏名，未映射）。"""
        raise NotImplementedError

    def build_records(self, row: dict, out: "Interim") -> Iterator[Record]:
        """把一行源记录变成 0..N 条 Record。产不出来的走 out.reject()。"""
        raise NotImplementedError

    # --- 已定，base 提供 ---
    def validate(self, rec: Record) -> list[str]:
        schema = self.schemas[rec.table]
        problems = []
        unknown = schema.unknown(rec.values)
        if unknown:
            problems.append(f"schema 无此列：{', '.join(unknown)}")
        missing = schema.missing_required(rec.values)
        if missing:
            problems.append(f"NOT NULL 列为空：{', '.join(missing)}")
        return problems

    def fill_absent(self, rec: Record) -> None:
        """把 mapping 声明填不了的列显式记成 null + 原因。

        不这么做的话，「这个源没有这个字段」与「这一行恰好是空」在 interim 里
        长得一模一样，CLAUDE.md 要求的区分就没了。
        """
        for col in self.mapping.not_available:
            rec.null_reasons.setdefault(col, NullReason.NOT_MAPPED)
        for col in self.mapping.platform_managed:
            rec.null_reasons.setdefault(col, NullReason.PLATFORM_MANAGED)

    def source_paths(self) -> list[tuple[Path, str]]:
        """本次实际读了哪些 raw 档。默认取 mapping 声明的 source_dataset(s)。

        这些档的 sha256 会进 _manifest.json —— 「这批 interim 由哪份原始快照产出」
        是证据链上不可省的一环。mapping 没声明输入档的源（如 sabdab），
        子类应覆写本方法把实际读的路径交回来。
        """
        out = []
        for name, spec in self.mapping.source_datasets:
            f = spec.get("file") if isinstance(spec, dict) else None
            if not f:
                continue
            p = Path(f) if Path(f).is_absolute() else ROOT / f
            if p.is_file():
                out.append((p, name))
        return out

    def assign_uid(self, rec: Record) -> None:
        raise Undecided("Q2", "SourceParser.assign_uid()")

    def should_include(self, rec: Record) -> bool:
        raise Undecided("Q4", "SourceParser.should_include()")

    # --- 主循环 ---
    def run(self, out: "Interim", *, limit: int | None = None) -> None:
        out.consume(self.mapping.path, "mapping")
        for t in self.targets:
            out.consume(self.schemas[t.table].origin, "schema", note=t.table)
        for path, note in self.source_paths():
            out.consume(path, "raw", note=note)
        n = 0
        for row in self.iter_source_rows():
            if limit is not None and n >= limit:
                break
            n += 1
            for rec in self.build_records(row, out):
                self.fill_absent(rec)
                problems = self.validate(rec)
                if problems:
                    out.reject(NullReason.VALIDATION_FAILED,
                               entity_key=rec.entity_key, problems=problems)
                    continue
                self.assign_uid(rec)              # Q2
                if not self.should_include(rec):  # Q4
                    continue
                out.emit(rec)
