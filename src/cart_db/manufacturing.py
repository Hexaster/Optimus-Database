"""Main-method identity and looser similarity; neither controls admission."""
from .measurements import convert

PROCESS_FIELDS = ('selection_steps', 'activation_method', 'vector_type', 'culture_system', 'culture_duration')


def duration(data, *, source_context=True):
    value = data.get('culture_duration')
    if not value or value.get('kind') == 'image_estimated_range':
        return None
    value = dict(value)
    value['unit'] = {'weeks': 'week', 'days': 'day', 'hours': 'h'}.get(value.get('unit'), value.get('unit'))
    value = convert(value, 'day')
    if value.get('unit') != 'day':
        return None
    keys = ('kind', 'value', 'lower', 'upper', 'error', 'unit')
    result = {key: value.get(key) for key in keys}
    if source_context:
        # Start/end points can be stated only in raw. Equal numbers alone imply
        # similarity, not proof of identical protocol timing.
        result['raw'] = value.get('raw')
    return result


def dimensions(data):
    steps = data.get('selection_steps')
    selection = None
    if steps and all(all(isinstance(step.get(k), str) and step[k].strip()
                         for k in ('input', 'output', 'method')) for step in steps):
        selection = [{k: step[k].strip() for k in ('input', 'output', 'method')} for step in steps]
    system = data.get('culture_system') or {}
    expansion = ({k: system[k].strip() for k in ('container', 'culture_mode')}
                 if all(isinstance(system.get(k), str) and system[k].strip()
                        for k in ('container', 'culture_mode')) else None)
    return dict(selection_steps=selection, activation_method=data.get('activation_method') or None,
                vector_type=data.get('vector_type') or None, culture_system=expansion,
                culture_duration=duration(data))


def process_key(data):
    values = dimensions(data)
    return values if all(v is not None for v in values.values()) else None


def similarity_key(data):
    value = duration(data, source_context=False)
    if data.get('vector_type') and value is not None:
        return dict(vector_type=data['vector_type'], culture_duration=value)
    return None


def compare_process(incoming, existing):
    a, b = dimensions(incoming), dimensions(existing)
    agreements = [k for k in a if a[k] is not None and a[k] == b[k]]
    differences = [k for k in a if a[k] is not None and b[k] is not None and a[k] != b[k]]
    unknown = [k for k in a if a[k] is None or b[k] is None]
    if not unknown and not differences:
        verdict, reason = 'same', '分选、激活、基因导入、扩增体系与周期一致。'
    elif similarity_key(incoming) is not None and similarity_key(incoming) == similarity_key(existing):
        verdict, reason = 'similar', '基因导入方式和培养周期一致，归为类似工艺，保留独立实体。'
    elif a['vector_type'] and b['vector_type'] and a['vector_type'] != b['vector_type']:
        verdict, reason = 'distinct', '基因导入方式不同。'
    elif duration(incoming, source_context=False) and duration(existing, source_context=False) and duration(incoming, source_context=False) != duration(existing, source_context=False):
        verdict, reason = 'distinct', '规范化后的培养周期不同。'
    else:
        verdict, reason = 'possible', '主要方法信息不足或文字描述不同，保留独立记录供来源审核。'
    return dict(verdict=verdict, agreements=agreements, differences=differences, unknown=unknown, reason=reason)
