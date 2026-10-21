"""Main-method identity and looser similarity; neither controls admission."""
from .measurements import convert

PROCESS_FIELDS = ('selection_steps', 'activation_method', 'vector_type', 'culture_system', 'culture_duration')


# Express reported duration in days; preserve timing wording for strict identity comparisons.
def duration(data, *, source_context=True):
    value = data.get('culture_duration')
    # Missing or image-estimated duration cannot support a strict protocol signature.
    if not value or value.get('kind') == 'image_estimated_range':
        return None
    value = dict(value)
    value['unit'] = {'weeks': 'week', 'days': 'day', 'hours': 'h'}.get(value.get('unit'), value.get('unit'))
    value = convert(value, 'day')
    # Keep duration unresolved when its unit cannot be converted to days.
    if value.get('unit') != 'day':
        return None
    keys = ('kind', 'value', 'lower', 'upper', 'error', 'unit')
    # Build mapped values from keys.
    result = {key: value.get(key) for key in keys}
    if source_context:
        # Start/end points can be stated only in raw. Equal numbers alone imply
        # similarity, not proof of identical protocol timing.
        result['raw'] = value.get('raw')
    return result


# Extract the five main process dimensions without guessing missing selection or culture details.
def dimensions(data):
    steps = data.get('selection_steps')
    selection = None
    # Selection is comparable only when every ordered step reports input, output, and method.
    if steps and all(all(isinstance(step.get(k), str) and step[k].strip()
                         for k in ('input', 'output', 'method')) for step in steps):
        # Build mapped values from steps.
        selection = [{k: step[k].strip() for k in ('input', 'output', 'method')} for step in steps]
    # Use an empty mapping when data.get('culture_system') is missing or empty.
    system = data.get('culture_system') or {}
    # Use {k: system[k].strip() for k in ('container', 'culture_mode')} when
    # all((isinstance(system.get(k), str) and system[k].strip() for k in ('container',
    # 'culture_mode'))); otherwise use None.
    expansion = ({k: system[k].strip() for k in ('container', 'culture_mode')}
                 if all(isinstance(system.get(k), str) and system[k].strip()
                        for k in ('container', 'culture_mode')) else None)
    # Apply the explicit fallbacks to missing/empty values while retaining any reported nonempty
    # values.
    return dict(selection_steps=selection, activation_method=data.get('activation_method') or None,
                vector_type=data.get('vector_type') or None, culture_system=expansion,
                culture_duration=duration(data))


# Return a strict process signature only when all five dimensions are known.
def process_key(data):
    values = dimensions(data)
    # Use values when all((v is not None for v in values.values())); otherwise use None.
    return values if all(v is not None for v in values.values()) else None


# Use delivery method and numeric duration for grouping, without claiming exact process identity.
def similarity_key(data):
    value = duration(data, source_context=False)
    # Both delivery method and a usable duration are needed for the weaker similarity key.
    if data.get('vector_type') and value is not None:
        return dict(vector_type=data['vector_type'], culture_duration=value)
    return None


# Compare complete methods first, then similarity and clear differences; retain uncertainty
# otherwise.
def compare_process(incoming, existing):
    a, b = dimensions(incoming), dimensions(existing)
    # Collect items from a only where a[k] is not None and a[k] == b[k].
    agreements = [k for k in a if a[k] is not None and a[k] == b[k]]
    # Collect items from a only where a[k] is not None and b[k] is not None and (a[k] != b[k]).
    differences = [k for k in a if a[k] is not None and b[k] is not None and a[k] != b[k]]
    # Collect items from a only where a[k] is None or b[k] is None.
    unknown = [k for k in a if a[k] is None or b[k] is None]
    # All main dimensions must be known and equal for an exact process match.
    if not unknown and not differences:
        verdict, reason = 'same', '分选、激活、基因导入、扩增体系与周期一致。'
    # Matching delivery and duration support similarity only; retain separate process identities.
    elif similarity_key(incoming) is not None and similarity_key(incoming) == similarity_key(existing):
        verdict, reason = 'similar', '基因导入方式和培养周期一致，归为类似工艺，保留独立实体。'
    # Different reported delivery methods establish distinct processes.
    elif a['vector_type'] and b['vector_type'] and a['vector_type'] != b['vector_type']:
        verdict, reason = 'distinct', '基因导入方式不同。'
    # Different comparable durations establish distinct processes even if other details are missing.
    elif duration(incoming, source_context=False) and duration(existing, source_context=False) and duration(incoming, source_context=False) != duration(existing, source_context=False):
        verdict, reason = 'distinct', '规范化后的培养周期不同。'
    # Incomplete or differently worded methods remain possible matches requiring source review.
    else:
        verdict, reason = 'possible', '主要方法信息不足或文字描述不同，保留独立记录供来源审核。'
    return dict(verdict=verdict, agreements=agreements, differences=differences, unknown=unknown, reason=reason)
