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


from cart_db.extraction import flatten
from cart_db.schema_models import KV, load_schema

SCHEMA = load_schema()
Extraction = SCHEMA.extraction
Combination = Extraction.model_fields["combinations"].annotation.__args__[0]


def _entity(kind):
    return next(e for e in SCHEMA.entities if e.kind == kind)


def _ev(kind, **kw):
    """一条能通过校验的最小证据。"""
    model = _entity(kind).evidence_model
    return model(source_type="literature", source_id="PMC1",
                 evidence_level="同行評議", **kw)


def _shared_ev(**kw):
    """组合实验用的证据（只有共享字段）。"""
    model = Combination.model_fields["experiments"].annotation.__args__[0]
    return model(source_type="literature", source_id="PMC1",
                 evidence_level="同行評議", **kw)


def _rows_of(rows, table):
    return [r for r in rows if r.table == table]


def test_evidence_points_at_its_own_binder():
    Binder = _entity("binder").model
    ex = Extraction(binders=[
        Binder(name="ARB-202", target_antigen="CDH17",
               evidence=[_ev("binder", kd=2.4, measurement_method="SPR")]),
        Binder(name="5F9", evidence=[_ev("binder", kd=40.0)]),
    ])
    rows = flatten(ex)
    binders = _rows_of(rows, "binder")
    by_kd = {e.data["binder.kd"]: e for e in _rows_of(rows, "evidence")}

    assert len(binders) == 2
    assert by_kd[2.4].data["binder.binder_id"] == binders[0].data["binder_id"]
    assert by_kd[40.0].data["binder.binder_id"] == binders[1].data["binder_id"]
    assert binders[0].data["binder_id"] != binders[1].data["binder_id"]


def test_evidence_carries_all_three_fk_columns():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["binder.binder_id"] is not None
    assert data["car.car_id"] is None
    assert data["manufacturing.manufacturing_id"] is None


def test_shared_fields_are_not_prefixed():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["source_id"] == "PMC1"
    assert "binder.source_id" not in data


def test_car_and_manufacturing_memory_phenotype_stay_apart():
    """同名字段必须写成两个不同的列，绝不能互相覆盖。"""
    Car = _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        cars=[Car(name="BBz", evidence=[_ev("car", memory_phenotype="Tcm 偏多")])],
        manufacturings=[Manufacturing(
            name="LV", evidence=[_ev("manufacturing", memory_phenotype="Tscm 偏多")])],
    )
    rows = _rows_of(flatten(ex), "evidence")
    values = {}
    for row in rows:
        values.update({k: v for k, v in row.data.items() if k.endswith("memory_phenotype")})
    assert values["car.memory_phenotype"] == "Tcm 偏多"
    assert values["manufacturing.memory_phenotype"] == "Tscm 偏多"


def test_kv_lists_become_dicts():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(
        name="A",
        fr_cdr_regions=[KV(key="CDR-H3", value="ARDYW")],
        evidence=[_ev("binder", measurement_conditions=[
            KV(key="温度", value="25°C"), KV(key="缓冲液", value="PBS")])],
    )])
    rows = flatten(ex)
    assert _rows_of(rows, "binder")[0].data["fr_cdr_regions"] == {"CDR-H3": "ARDYW"}
    assert _rows_of(rows, "evidence")[0].data["binder.measurement_conditions"] == {
        "温度": "25°C", "缓冲液": "PBS"}


def test_modules_stay_a_list():
    Car = _entity("car").model
    ex = Extraction(cars=[Car(name="BBz", modules=[
        {"module_type": "hinge", "source_molecule": "CD8a", "length": 45},
        {"module_type": "CD3zeta"},
    ])])
    modules = _rows_of(flatten(ex), "car")[0].data["modules"]
    assert isinstance(modules, list) and len(modules) == 2
    assert modules[0]["module_type"] == "hinge"


def test_entities_come_before_evidence():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    tables = [r.table for r in flatten(ex)]
    assert tables.index("binder") < tables.index("evidence")


def test_combination_resolves_indices_and_emits_one_evidence_row():
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A"), Binder(name="B")],
        cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV-MOI5")],
        combinations=[Combination(
            binder_index=1, car_index=0, manufacturing_index=0,
            completed_experiment_phase="in_vitro",
            experiments=[_shared_ev(outcomes=[KV(key="killing_rate", value="85%")])],
        )],
    )
    rows = flatten(ex)
    combo = _rows_of(rows, "abc_combination_db1")[0]
    evidence = _rows_of(rows, "evidence")[0]

    assert combo.data["binder_id"] == _rows_of(rows, "binder")[1].data["binder_id"]
    assert combo.data["completed_experiment_phase"] == "in_vitro"
    assert evidence.data["binder.binder_id"] == combo.data["binder_id"]
    assert evidence.data["car.car_id"] == combo.data["car_id"]
    assert evidence.data["manufacturing.manufacturing_id"] == combo.data["manufacturing_id"]
    assert evidence.data["outcomes"] == {"killing_rate": "85%"}


def test_out_of_range_combination_is_dropped(caplog):
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A")], cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV")],
        combinations=[Combination(binder_index=7, car_index=0, manufacturing_index=0)],
    )
    with caplog.at_level("WARNING"):
        rows = flatten(ex)
    assert _rows_of(rows, "abc_combination_db1") == []
    assert "序号越界" in caplog.text


def test_negative_index_is_dropped():
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A")], cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV")],
        combinations=[Combination(binder_index=-1, car_index=0, manufacturing_index=0)],
    )
    assert _rows_of(flatten(ex), "abc_combination_db1") == []


def test_evidence_without_source_id_is_dropped(caplog):
    Binder = _entity("binder").model
    model = _entity("binder").evidence_model
    ex = Extraction(binders=[Binder(name="A", evidence=[
        model(source_type="literature", source_id=None,
              evidence_level="同行評議", kd=2.4)])])
    with caplog.at_level("WARNING"):
        rows = flatten(ex)
    assert _rows_of(rows, "evidence") == []
    assert _rows_of(rows, "binder") != []       # 实体本身保留
    assert "出处" in caplog.text


def test_evidence_with_blank_evidence_level_is_dropped():
    Binder = _entity("binder").model
    model = _entity("binder").evidence_model
    ex = Extraction(binders=[Binder(name="A", evidence=[
        model(source_type="literature", source_id="PMC1", evidence_level="   ")])])
    assert _rows_of(flatten(ex), "evidence") == []


import json

from cart_db import extraction


def test_system_prompt_contains_rules_schema_and_output_guide():
    prompt = extraction.build_system_prompt()
    assert "biomedical data extraction agent" in prompt      # article_extraction_prompt.txt
    assert "target_antigen" in prompt                        # Schema_A.yaml
    assert "abc_combination_db1" in prompt                   # Schema_DB1.yaml
    assert "binder.kd" in prompt                             # Evidence.yaml
    assert "binder_index" in prompt                          # 输出格式说明


def test_system_prompt_is_stable_across_calls():
    """跨文档完全一致才能命中提示词缓存。"""
    assert extraction.build_system_prompt() == extraction.build_system_prompt()


def test_extract_document_writes_jsonl(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    Binder = _entity("binder").model
    captured = {}

    def fake_extract(*, schema, document, system_prompt, purpose, **kw):
        captured.update(document=document, purpose=purpose, schema=schema)
        return Extraction(binders=[
            Binder(name="ARB-202", evidence=[_ev("binder", kd=2.4)])])

    monkeypatch.setattr(extraction.llm, "extract", fake_extract)
    out_dir = tmp_path / "out"
    rows = extraction.extract_document(doc, out_dir=out_dir)

    assert "Kd = 2.4 nM" in captured["document"]      # 正文送进去了
    assert "Smith 2020" not in captured["document"]   # 参考文献没送
    assert captured["purpose"] == "article_extraction"
    assert captured["schema"] is SCHEMA.extraction

    written = (out_dir / "PMC1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(written) == len(rows) == 2
    assert json.loads(written[0])["data"]["name"] == "ARB-202"


def test_extract_document_writes_readable_utf8(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    Binder = _entity("binder").model
    monkeypatch.setattr(extraction.llm, "extract",
                        lambda **kw: Extraction(binders=[Binder(name="抗体")]))

    extraction.extract_document(doc, out_dir=tmp_path / "out")
    raw = (tmp_path / "out" / "PMC1.jsonl").read_text(encoding="utf-8")
    assert "抗体" in raw


def test_dry_run_estimates_without_calling_extract(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")

    def boom(**kw):
        raise AssertionError("dry_run 不该真的调用模型")

    monkeypatch.setattr(extraction.llm, "extract", boom)
    monkeypatch.setattr(extraction.llm, "count_tokens", lambda **kw: 42_000)

    rows = extraction.extract_document(doc, out_dir=tmp_path / "out", dry_run=True)
    assert rows == []
    assert not (tmp_path / "out" / "PMC1.jsonl").exists()
