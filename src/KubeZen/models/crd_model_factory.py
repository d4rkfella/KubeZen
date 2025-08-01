from __future__ import annotations
from datetime import datetime
from kubernetes_asyncio.client.models import V1CustomResourceDefinition
from dataclasses import make_dataclass, Field
from typing import Type, cast, Union, Any
from KubeZen.models.base import (
    UIRow,
    CATEGORIES,
    logging,
    column_field,
    ApiInfo,
)

log = logging.getLogger(__name__)


def create_model_from_crd(crd: V1CustomResourceDefinition) -> Type[UIRow]:
    spec = crd.spec
    group = spec.group
    names = spec.names
    plural = names.plural
    kind = names.kind
    scope = spec.scope
    versions = spec.versions

    storage_version = next((v for v in versions if v.storage), versions[0])
    storage_version_name = storage_version.name
    printer_cols = getattr(storage_version, "additional_printer_columns", []) or []

    fields: list[tuple[str, Type[Union[str, datetime]], Field]] = [
        ("age", datetime, column_field(label="Age", is_age=True, index=999))
    ]

    init_body_lines = ["super(self.__class__, self).__init__(raw)"]

    for i, col in enumerate(printer_cols):
        if col.name.lower() == "age":
            continue

        label = col.name
        source_path = col.json_path.lstrip(".")
        is_age = "lastTransitionTime" in source_path
        field_name = f"col_{label.lower().replace(' ', '_').replace('-', '_')}"

        fields.append(
            (field_name, str, column_field(label=label, is_age=is_age, index=2 + i))
        )

        init_body_lines.append(f"val = self._resolve_path(raw, {repr(source_path)})")

        if is_age:
            init_body_lines.append("if isinstance(val, str):")
            init_body_lines.append("    val = UIRow.to_datetime(val)")
            init_body_lines.append(f"object.__setattr__(self, '{field_name}', val)")
        else:
            init_body_lines.append(f"object.__setattr__(self, '{field_name}', val)")

    full_init_src = "def __init__(self, raw):\n" + "\n".join(
        f"    {line}" for line in init_body_lines
    )
    local_ns: dict[str, Any] = {}
    exec(full_init_src, globals(), local_ns)
    custom_init = local_ns["__init__"]

    model_cls = make_dataclass(
        kind + "Row",
        fields,
        bases=(UIRow,),
        frozen=True,
        namespace={
            "__init__": custom_init,
            "kind": kind,
            "plural": plural,
            "namespaced": scope == "Namespaced",
            "display_name": kind,
            "category": CATEGORIES["Custom Resources"].name,
            "api_info": ApiInfo(
                client_name="CustomObjectsApi",
                group=group,
                version=storage_version_name,
            ),
            "index": 99,
        },
    )
    return cast(Type[UIRow], model_cls)
