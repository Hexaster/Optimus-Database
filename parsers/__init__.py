"""结构化源的 parser。

parser 的定义（业务侧 2026-08-24 确认）：
    输入 raw data + mapping doc + schema，输出 normalised data ready to enter the db。

只做映射这一件事：不取数（downloaders/），不写库（后续 loader）。
公共契约见 base.py；每个源一个模块，继承 SourceParser。

范围：只收**结构化**源，即能栏对栏映射的。EMA / FDA 的 PDF 与 Europe PMC 的全文
靠 LLM 抽取，按 blueprint 归 Prompts 那一支，不在这里。
"""

#: mapping_id → 本目录下的模块名。
#
# 为什么放在代码里而不是 mapping doc 里：downloaders 的对位设计是把 `downloader:`
# 写进 registry 的「下载配置」块（文档驱动代码）。这里本该同构，在 mapping doc 里
# 加一个 `parser:` 键。但 docs 与 sql 的 schema 差异尚未收敛，三份 mapping 都要重修，
# 现在往里加键只会跟那次修改打架。**这是一处有意的临时偏离**，mapping 定稿后
# 应把这张表挪进各自的 mapping doc，本文件只留导入逻辑。
KNOWN_PARSERS: dict[str, str] = {
    "thera_sabdab_to_binder": "thera_sabdab",
    "dotad_to_binder": "dotad",
    "sabdab_to_binder": "sabdab",
}
