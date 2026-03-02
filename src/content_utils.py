"""Shared content_data traversal utilities.

Provides walk_content_data() to apply a transform function to all
visible text fields in a slide's content_data dict. Used by both
citation stripping (llm.py) and hash stripping (renderer.py) to
eliminate duplicated field-name lists.

The CONTENT_FIELD_MAP constant matches the field categories used by:
  - _clean_slide_text (src/llm.py)
  - _strip_content_data_hashes (src/renderer.py)
Note: the update_slide_content_text SQL trigger uses a subset of these fields.
"""

from typing import Callable

CONTENT_FIELD_MAP: dict = {
    "scalar": ["statement", "subtitle", "caption", "code_block"],
    "list": ["bullets", "left_items", "right_items", "explain_bullets", "callouts"],
    "nested": {"steps": ["label", "caption"]},
}


def build_global_field_map(slide_type_configs: dict) -> dict:
    """Merge per-type content_fields into a single global field map.

    Used at startup to replace the hardcoded CONTENT_FIELD_MAP with
    a map derived from slide_type_config rows in Postgres.
    """
    scalars: set[str] = set()
    lists: set[str] = set()
    nested: dict[str, set[str]] = {}

    for config in slide_type_configs.values():
        cf = config.get("content_fields", {})
        scalars.update(cf.get("scalar", []))
        lists.update(cf.get("list", []))
        for parent, children in cf.get("nested", {}).items():
            if parent not in nested:
                nested[parent] = set()
            nested[parent].update(children)

    return {
        "scalar": sorted(scalars),
        "list": sorted(lists),
        "nested": {k: sorted(v) for k, v in nested.items()},
    }


def init_content_field_map(slide_type_configs: dict) -> None:
    """Replace CONTENT_FIELD_MAP with a DB-derived merged field map.

    Called at startup after load_slide_type_configs(). If slide_type_configs
    is empty (pre-startup or DB unavailable), leaves CONTENT_FIELD_MAP unchanged.
    """
    global CONTENT_FIELD_MAP
    if not slide_type_configs:
        return
    CONTENT_FIELD_MAP = build_global_field_map(slide_type_configs)


def walk_content_data(
    cd: dict,
    fn: Callable[[str], str],
    fields: dict | None = None,
) -> dict:
    """Apply fn to all visible text fields in content_data.

    Args:
        cd: The content_data dict from a slide (mutated in place).
        fn: A str->str transform applied to each text value.
        fields: Field map with "scalar", "list", "nested" keys.
                Defaults to CONTENT_FIELD_MAP if not provided.

    Returns:
        The mutated cd dict (same reference), or cd unchanged if falsy.
    """
    if not cd:
        return cd
    if fields is None:
        fields = CONTENT_FIELD_MAP

    for key in fields.get("scalar", []):
        if key in cd and isinstance(cd[key], str):
            cd[key] = fn(cd[key])

    for key in fields.get("list", []):
        if key in cd and isinstance(cd[key], list):
            cd[key] = [
                fn(item) if isinstance(item, str) else item
                for item in cd[key]
            ]

    for parent_key, child_keys in fields.get("nested", {}).items():
        if parent_key in cd and isinstance(cd[parent_key], list):
            for item in cd[parent_key]:
                if isinstance(item, dict):
                    for k in child_keys:
                        if k in item and isinstance(item[k], str):
                            item[k] = fn(item[k])

    return cd
