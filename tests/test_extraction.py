"""文档读取与拆平逻辑的测试。不联网、不调模型。"""
import pytest

from cart_db.extraction import load_document, strip_xml_boilerplate

JATS = """<article>
  <front><article-title>Anti-CDH17 CAR-T</article-title></front>
  <body><p>SPR 测得 Kd = 2.4 nM。</p></body>
  <back>
    <ack><p>感谢基金支持。</p></ack>
    <ref-list><ref><mixed-citation>Smith 2020</mixed-citation></ref></ref-list>
  </back>
</article>"""


def test_strip_removes_back_matter():
    out = strip_xml_boilerplate(JATS)
    assert "Smith 2020" not in out
    assert "感谢基金支持" not in out


def test_strip_keeps_body_intact():
    out = strip_xml_boilerplate(JATS)
    assert "Kd = 2.4 nM" in out
    assert "Anti-CDH17 CAR-T" in out


def test_strip_removes_standalone_ref_list():
    xml = "<article><body><p>正文</p></body><ref-list><ref>X</ref></ref-list></article>"
    out = strip_xml_boilerplate(xml)
    assert "正文" in out
    assert "<ref>" not in out


def test_load_xml_file(tmp_path):
    path = tmp_path / "PMC1.xml"
    path.write_text(JATS, encoding="utf-8")
    text = load_document(path)
    assert "Kd = 2.4 nM" in text
    assert "Smith 2020" not in text


def test_load_nxml_extension(tmp_path):
    path = tmp_path / "PMC1.nxml"
    path.write_text(JATS, encoding="utf-8")
    assert "Kd = 2.4 nM" in load_document(path)


def test_load_markdown_verbatim(tmp_path):
    """Markdown 已经是纯文本，原样送进去，不做任何剥离。"""
    path = tmp_path / "note.md"
    path.write_text("# 实验记录\n\nKd = 2.4 nM\n\n<ref-list>保留</ref-list>\n", encoding="utf-8")
    text = load_document(path)
    assert "# 实验记录" in text
    assert "Kd = 2.4 nM" in text
    assert "<ref-list>保留</ref-list>" in text


def test_load_markdown_alias_extension(tmp_path):
    path = tmp_path / "note.markdown"
    path.write_text("Kd = 2.4 nM\n", encoding="utf-8")
    assert "Kd = 2.4 nM" in load_document(path)


def test_unknown_extension_raises(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的文件格式"):
        load_document(path)
