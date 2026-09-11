#!/usr/bin/env python3
"""把某模型某文档的抽取结果与人工基准逐条语义比对（v2）。

    python3 judge_v2.py <结果目录> <模型名> [文档前缀]

相对 v1 的三处改动，都对应实测查出的判错：
  【1】**把原文交给判定器**。v1 只能看基准和抽取两份二手材料，
       导致「was observed」「胸腺阳性」「CDR SEQ ID」等至少 16 处判反
       ——这些内容都是原文白纸黑字写着的。现在凡是判 extra/value_mismatch
       的，必须给出原文引文或明说找不到。
  【2】**字段名必须可定位**。v1 有 64% 的差异 field 写的是描述性文字
       （"ELISA screening evidence"），无法回连抽取结果做失效模式诊断。
       现在把 schema 真实字段清单给它，只准从中选。
  【3】**直接输出三分归因**，不再靠事后人工分诊。
       并对已知的基准缺陷（evidence_level 已注释、图内估读）预先豁免。
"""
import json, re, sys, time, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GT   = ROOT.parent/"模型评测/组5_自身免疫-CD19/02_人工答案/五表"
SRC  = ROOT/"01_原始文档"
CMP  = ROOT/"03_比对_v2"
TABLES = ["binder","car","manufacturing","abc_combination_db1","evidence"]
T2F = {"binder":"A_binder","car":"B_car","manufacturing":"C_manufacturing",
       "abc_combination_db1":"ABC_combination","evidence":"evidence"}
DOCS = {"paper-A":"PMC11176803","paper-B":"PMC12221509","patent-C":"US-2023074145-A1"}

def source_text(doc_key: str) -> str:
    p = next(SRC.glob(f"{doc_key}_*"), None)
    if p is None: return ""
    if p.suffix.lower() == ".pdf":
        return subprocess.run(["pdftotext","-layout",str(p),"-"],
                              capture_output=True, text=True).stdout
    return p.read_text(encoding="utf-8", errors="replace")

def load_gt(source_id: str) -> dict:
    ev = [json.loads(l) for l in (GT/"evidence.jsonl").open(encoding="utf-8") if l.strip()]
    ev = [r for r in ev if r.get("source_id") == source_id]
    ids = {k:set() for k in ("binder","car","manufacturing")}
    for r in ev:
        for k in ids:
            v = r.get(f"{k}.{k}_id") or r.get(f"{k}_id")
            if v: ids[k].add(v)
    out = {"evidence": ev}
    for t,f in T2F.items():
        if t == "evidence": continue
        rows = [json.loads(l) for l in (GT/f"{f}.jsonl").open(encoding="utf-8") if l.strip()]
        if t in ids and ids[t]:
            rows = [r for r in rows if r.get(f"{t}_id") in ids[t]] or rows
        out[t] = rows
    return out

def load_ext(d: Path, stem: str) -> dict:
    f = d/f"{stem}.jsonl"
    if not f.is_file(): return {}
    o = {t:[] for t in TABLES}
    for l in f.open(encoding="utf-8"):
        if not l.strip(): continue
        r = json.loads(l)
        o.setdefault(r["table"], []).append(r.get("data", {}))
    return o

def field_list(gt, ext) -> list[str]:
    s = set()
    for src in (gt, ext):
        for t, rows in src.items():
            for r in rows:
                for k in r: s.add(f"{t}.{k}")
    return sorted(s)

SYS = """你把一份自动抽取结果与人工基准逐条比对。**判定靠推理，不靠字符串相等。**
你会同时拿到**文档原文**——这是裁决的最终依据。

以下都不算差异：
- 主键 UUID 不同；数值等价但单位写法不同；实体名措辞不同但指同一对象
- 中英文对照；证据行拆分粒度不同但覆盖的事实集合一致；null 与"未报告"等价

**已知基准缺陷 / 取材限制——按下列程序处理，不得凭印象判断：**

(A) `evidence_level`：该字段在当前 schema 里已被注释掉，不是活跃字段。
    基准里带 0.5/0.75 是照旧 schema 建的。抽取方留空是对的。
    → **完全不要输出**，放进 equivalences。

(B) **图内数值：判任何数值为 missing_in_extraction 之前，必须先看基准该值的
    `raw` 字段,并按下表分流。这是强制步骤,不是可选提示。**

    | `raw` 里出现 | 含义 | 判法 |
    |---|---|---|
    | `估读` / `估计` / 只写 `Figure N` 而无数字 | 数值是从柱高、曲线量出来的 | cause=`figure_only`，pile=`source_unavailable`，**绝不可判 model** |
    | `图内直印数字` / `图中直印` | 数字**印在图上**，页图已随请求提供 | 正常判定；漏抽算 `missing_in_extraction` / model |
    | 无图相关字样 | 正文或表格可得 | 正常判定 |

    典型 `raw` 实例（照此识别）：
      `Figure 1D 估读 7480 ± 3620 pg/mL（mean ± SD，n=4 供者）`  → figure_only
      `CABA-201：CAR⁺ 门内 52.1 %（Figure 1A 图内直印数字）`      → 正常判定

    本轮 paper-A 的基准中，`manufacturing.cytokine_release` 有 13 处、
    `manufacturing.transduction_efficiency` 有 9 处带图相关标记，
    **逐一按上表分流，不要整类跳过、也不要整类算到模型头上。**

**裁决规则（必须遵守）：**
1. 判 `extra_in_extraction` 或 `value_mismatch` 前，**必须先在原文中检索**。
   若原文支持抽取方，则不是模型的错——是基准漏收或基准有误。
2. 每处差异的 `field` **必须从给定的字段清单中选**，原样照抄，不得自造描述性名称。
3. 若你判断某项"不算错误"，**就不要把它放进 differences**，放进 equivalences。

对每处差异判定**成因**与**归属**：
成因 cause ∈ missing_in_extraction / extra_in_extraction / value_mismatch /
             unit_or_scale_error / attribution_error / figure_only / schema_limitation / ambiguous_source
归属 pile  ∈ model（模型的错）/ ground_truth（基准的错）/ source_unavailable（原文未提供该内容）

**cause 与 pile 的强制对应**：`figure_only` 必须配 `source_unavailable`；
反之，凡是基准 `raw` 带 `估读` 的数值，cause 必须是 `figure_only`，不得写成
`missing_in_extraction`。这条不满足即为判定错误。

只输出 JSON：
{"summary":{"real_differences":N,"by_pile":{"model":N,"ground_truth":N,"source_unavailable":N}},
 "differences":[{"table":"...","field":"<字段清单中的一项>","ground_truth":"...","extracted":"...",
                 "cause":"...","pile":"...","source_quote":"原文原句；找不到就写 NOT_FOUND",
                 "reasoning":"一到两句"}],
 "equivalences":[{"field":"...","note":"判为等价的理由"}]}"""

def _env():
    return {l.split("=",1)[0]: l.split("=",1)[1].strip()
            for l in (ROOT.parent/"Fosun-db-master 2/.env").open()
            if "=" in l and not l.startswith("#")}

def _call(jm: str, sys_p: str, user: str):
    """判定器可换家。2026-09-11 OpenAI 余额耗尽，故补 Anthropic 通道。
    返回 (文本, 输入token, 输出token)。"""
    if jm.startswith("claude"):
        import anthropic
        c = anthropic.Anthropic(api_key=_env().get("ANTHROPIC_API_KEY") or None, timeout=1800)
        with c.messages.stream(model=jm, max_tokens=32000,
                system=[{"type":"text","text":sys_p,
                         "cache_control":{"type":"ephemeral","ttl":"1h"}}],
                messages=[{"role":"user","content":user}],
                thinking={"type":"adaptive"}) as st:
            m = st.get_final_message()
        txt = "".join(b.text for b in m.content if getattr(b,"type","")=="text")
        return txt, m.usage.input_tokens, m.usage.output_tokens
    from openai import OpenAI
    c = OpenAI(api_key=_env()["OPENAI_API_KEY"], timeout=1800)
    r = c.responses.create(model=jm, max_output_tokens=48000, reasoning={"effort":"high"},
        input=[{"role":"system","content":sys_p},{"role":"user","content":user}])
    return r.output_text, r.usage.input_tokens, r.usage.output_tokens

def judge(res_dir: Path, model: str, stem: str, doc_key: str, jm="claude-opus-5"):
    ext, gt = load_ext(res_dir, stem), load_gt(DOCS[doc_key])
    if not ext: return None
    src = source_text(doc_key)
    fields = field_list(gt, ext)
    payload = json.dumps({"ground_truth":{k:gt.get(k,[]) for k in TABLES},
                          "extracted":{k:ext.get(k,[]) for k in TABLES}}, ensure_ascii=False)
    user = (f"文档：{doc_key}（{DOCS[doc_key]}）　抽取模型：{model}\n\n"
            f"=== 可用字段清单（field 只能从这里选）===\n{json.dumps(fields,ensure_ascii=False)}\n\n"
            f"=== 文档原文 ===\n{src[:420_000]}\n\n"
            f"=== 基准与抽取 ===\n{payload[:420_000]}")
    out, tin, tout = _call(jm, SYS, user)
    m = re.search(r"\{.*\}", out, re.S)
    if not m: return {"error":"未返回 JSON","raw":out[:800]}
    try: res = json.loads(m.group(0))
    except Exception as e: return {"error":f"JSON 解析失败 {e}","raw":r.output_text[:800]}
    # 字段名合法性自检
    legal = set(fields)
    bad = [d.get("field") for d in res.get("differences",[])
           if f"{d.get('table')}.{str(d.get('field','')).split('.')[-1]}" not in legal
           and d.get("field") not in legal]
    res["_meta"] = {"model":model,"doc":doc_key,"judge":jm,"源文本字符":len(src),
                    "字段清单":len(fields),"字段名不可定位":len(bad),
                    "judge_in":tin,"judge_out":tout}
    return res

if __name__ == "__main__":
    res_dir = Path(sys.argv[1]); model = sys.argv[2]
    want = sys.argv[3] if len(sys.argv) > 3 else None
    jm   = sys.argv[4] if len(sys.argv) > 4 else "claude-opus-5"
    # 换判定器时另存一份，便于比较不同判定器给出的结论（判定器本身也有方差）
    CMP = ROOT/"03_比对_v2" if jm == "claude-opus-5" else ROOT/f"03_比对_v2_{jm}"
    CMP.mkdir(exist_ok=True)
    for p in sorted(res_dir.glob("*.jsonl")):
        if p.name.endswith("errors.jsonl"): continue
        key = next((k for k in DOCS if p.stem.startswith(k)), None)
        if not key or (want and key != want): continue
        t0 = time.monotonic()
        res = judge(res_dir, model, p.stem, key, jm)
        if res is None: continue
        f = CMP/f"{model}__{key}.json"
        f.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        s = res.get("summary",{}); mm = res.get("_meta",{})
        print(f"  {model:<15}{key:<10}{time.monotonic()-t0:>5.0f}s  "
              f"差异 {s.get('real_differences','?'):>3}  {s.get('by_pile',{})}  "
              f"原文 {mm.get('源文本字符',0):,} 字  字段不可定位 {mm.get('字段名不可定位','?')}")
