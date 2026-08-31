"""模型必须完全由 docs/Schema/*.yaml 决定 —— 改 YAML 就该改模型，不用动 Python。"""
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cart_db import llm
from cart_db.schema_models import load_schema

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docs" / "Schema"


def _yaml_fields(filename: str, table_key: str) -> dict:
    doc = yaml.safe_load((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    return doc[table_key]["fields"]


def _entity(schema, kind):
    return next(e for e in schema.entities if e.kind == kind)


def test_shared_evidence_fields_come_from_yaml():
    fields = _yaml_fields("Evidence.yaml", "evidence")
    expected = {name for name in fields if "." not in name} - {"record_id"}
    assert set(load_schema().shared_evidence_fields) == expected


def test_each_prefix_becomes_its_own_evidence_model():
    schema = load_schema()
    fields = _yaml_fields("Evidence.yaml", "evidence")
    for kind in ("binder", "car", "manufacturing"):
        expected = {
            name.split(".", 1)[1] for name in fields if name.startswith(f"{kind}.")
        } - {f"{kind}_id"}
        model = _entity(schema, kind).evidence_model
        actual = set(model.model_fields) - set(schema.shared_evidence_fields)
        assert actual == expected, f"{kind} 的证据字段与 Evidence.yaml 不一致"


def test_same_field_name_under_two_prefixes_does_not_collide():
    """car.memory_phenotype 与 manufacturing.memory_phenotype 同名不同表。

    合并成一个扁平证据模型的话，其中一个会被静默覆盖，数据从此对不上。
    """
    schema = load_schema()
    car = _entity(schema, "car").evidence_model
    manufacturing = _entity(schema, "manufacturing").evidence_model

    assert "memory_phenotype" in car.model_fields
    assert "memory_phenotype" in manufacturing.model_fields
    assert car is not manufacturing
    # 只有 manufacturing 有 exhaustion_phenotype，只有 car 有 persistence
    assert "exhaustion_phenotype" in manufacturing.model_fields
    assert "exhaustion_phenotype" not in car.model_fields
    assert "persistence" in car.model_fields
    assert "persistence" not in manufacturing.model_fields


def test_entity_models_match_yaml():
    schema = load_schema()
    cases = [("binder", "Schema_A.yaml", "binder", "binder_id"),
             ("car", "Schema_B.yaml", "car", "car_id"),
             ("manufacturing", "Schema_C.yaml", "manufacturing", "manufacturing_id")]
    for kind, filename, table_key, pk in cases:
        expected = set(_yaml_fields(filename, table_key)) - {pk}
        model = _entity(schema, kind).model
        assert set(model.model_fields) - {"evidence"} == expected


def test_primary_and_foreign_keys_are_never_asked_of_the_model():
    """编号由 flatten() 生成，让模型填就等于让它编。"""
    schema = load_schema()
    assert "binder_id" not in _entity(schema, "binder").model.model_fields
    assert "binder_id" not in _entity(schema, "binder").evidence_model.model_fields
    assert "record_id" not in _entity(schema, "binder").evidence_model.model_fields


def test_allowed_values_become_a_closed_choice():
    model = _entity(load_schema(), "manufacturing").model
    assert model(t_cell_source="自体").t_cell_source == "自体"
    with pytest.raises(ValidationError):
        model(t_cell_source="autologous")


def test_json_field_without_item_schema_becomes_a_plain_string():
    """没有 item_schema 的 json 字段现在是一段自由文本，不再是键值对列表。

    键值对列表在 20+ 个可空字段时会把强制格式 grammar 撑爆（见阻塞报告）。
    """
    binder = _entity(load_schema(), "binder").model
    assert binder.model_fields["fr_cdr_regions"].annotation is str
    built = binder(fr_cdr_regions="CDR-H3: ARDYW")
    assert built.fr_cdr_regions == "CDR-H3: ARDYW"

    # 有 item_schema 的字段（car.modules）不受影响，仍然是嵌套模型。
    car = _entity(load_schema(), "car").model
    assert car.model_fields["modules"].annotation is not str
    built_car = car(modules=[{"module_type": "hinge", "source_molecule": "CD8a", "length": 45}])
    assert built_car.modules[0].module_type == "hinge"


def test_item_schema_becomes_a_nested_model():
    """Schema_B.yaml 的 car.modules 带 item_schema，应生成真正的子模型。"""
    model = _entity(load_schema(), "car").model
    built = model(modules=[{"module_type": "hinge", "source_molecule": "CD8a", "length": 45}])
    assert built.modules[0].module_type == "hinge"
    with pytest.raises(ValidationError):
        model(modules=[{"module_type": "不存在的模块类型"}])


def test_combination_foreign_keys_become_indices():
    combination = load_schema().extraction.model_fields["combinations"].annotation
    fields = combination.__args__[0].model_fields
    assert {"binder_index", "car_index", "manufacturing_index"} <= set(fields)
    assert "binder_id" not in fields
    assert "combination_id" not in fields
    assert "experiments" in fields


def test_root_model_has_four_lists():
    assert set(load_schema().extraction.model_fields) == {
        "binders", "cars", "manufacturings", "combinations"}


def test_requests_have_one_field_each_in_call_order():
    """每次 LLM 调用只问一张表，顺序固定：combinations 要靠前三次的结果填索引。"""
    schema = load_schema()
    names = [name for name, _ in schema.requests]
    assert names == ["binders", "cars", "manufacturings", "combinations"]

    extraction_fields = schema.extraction.model_fields
    for name, model in schema.requests:
        assert set(model.model_fields) == {name}
        assert model.model_fields[name].annotation == extraction_fields[name].annotation


def test_strict_schema_is_not_empty():
    """回归测试：旧版 data: dict[str, Any] 会被 _strict 变成「一个字段都不准填」。"""
    schema = llm._strict(load_schema().extraction.model_json_schema())
    binder = next(v for k, v in schema["$defs"].items() if k == "Binder")
    assert binder["additionalProperties"] is False
    assert "vh_sequence" in binder["properties"]
    assert set(binder["required"]) == set(binder["properties"])


def test_new_yaml_field_appears_without_touching_python(tmp_path):
    """这条测试就是本任务存在的理由：加字段只改 YAML。"""
    schema_dir = tmp_path / "Schema"
    shutil.copytree(SCHEMA_DIR, schema_dir)
    path = schema_dir / "Schema_A.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n    isotype:\n      type: string\n      nullable: true\n"
          "      description: 抗体亚型。\n",
        encoding="utf-8",
    )
    model = _entity(load_schema(schema_dir), "binder").model
    assert "isotype" in model.model_fields


def test_prefix_group_overlapping_a_shared_field_is_rejected(tmp_path):
    schema_dir = tmp_path / "Schema"
    shutil.copytree(SCHEMA_DIR, schema_dir)
    path = schema_dir / "Evidence.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n    binder.citation:\n      type: string\n      nullable: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="与共享字段重名"):
        load_schema(schema_dir)


def test_load_schema_default_and_explicit_none_are_the_same_object():
    from cart_db.schema_models import SCHEMA_DIR, load_schema
    assert load_schema() is load_schema(None)
    assert load_schema() is load_schema(SCHEMA_DIR)
