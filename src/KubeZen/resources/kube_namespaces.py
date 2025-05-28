#!/usr/bin/env python3
from typing import List, Tuple, Optional, Union, TYPE_CHECKING

# Forward declaration for type hinting
if TYPE_CHECKING:
    from .kube_base import KubeBase

class NamespaceManager:
    resource_type = "namespaces"
    resource_name = "Namespace"

    def __init__(self, base: 'KubeBase'):
        self.base = base

    def _refresh_resources(self, namespace: Optional[str] = None) -> Optional[List[str]]:
        return self.base.kubectl_client.get_resources(self.resource_type, None)

    def select_resource(self, resources: Optional[List[str]] = None, title: Optional[str] = None, include_common_elements: Union[bool, List[str]] = True) -> Optional[Tuple[str, str]]:
        actual_resources = resources if resources is not None else self._refresh_resources()
        if actual_resources is None:
            return None 

        if not actual_resources:
            print("No namespaces found or accessible.")
            input("\nPress Enter to continue...")
            return None

        actual_title = title if title else "Select Namespace"
        
        preview_cmd_template = None
        if self.base.resource_type and self.base.resource_type != "namespaces":
            preview_cmd_template = self.base.kubectl_client.get_command_template(
                action="get", 
                resource_type=self.base.resource_type,
                namespace="{1}",
                extra_args=["--no-headers", "-Lapp", "-Lapp.kubernetes.io/component"]
            )
        else:
            preview_cmd_template = self.base.kubectl_client.get_command_template(
                action="get", 
                resource_type=self.resource_type,
                name="{1}",
                output_format="yaml"
            )
        ns_select_bindings = ["--bind", "enter:accept"] 
        ns_select_header = "Enter: Select Namespace"

        return self.base.run_fzf(
            items=actual_resources,
            title=actual_title,
            extra_header=ns_select_header,
            extra_bindings=ns_select_bindings,
            include_common_elements=include_common_elements, 
            preview_command_template=preview_cmd_template,
            preview_window_settings="right:60%:wrap"
        ) 