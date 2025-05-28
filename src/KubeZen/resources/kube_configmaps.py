#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from .kube_base import KubeBase
import sys
import json

class ConfigMapManager(KubeBase):
    resource_type = "configmaps"
    resource_name = "ConfigMap"

    def __init__(self):
        super().__init__()

    def _get_resource_fzf_elements(self) -> List[dict]:
        return [
            {"fzf_bind_action": "alt-v:accept", "header_text": "Alt-V: View Content"},
        ]

    def _get_resource_actions(self):
        """Provide configmap-specific actions"""
        return {
            "alt-v": self._view_content
        }

    def _view_content(self, configmap_name: str):
        """View configmap data using KubectlClient."""
        subprocess.run(["clear"])
        print(f"Fetching data for ConfigMap '{configmap_name}' in namespace '{self.current_namespace}'...")
        
        configmap_spec = self.kubectl_client.get_resource_spec("configmap", configmap_name, self.current_namespace)

        if not configmap_spec:
            input("\nPress Enter to continue...")
            return

        try:
            if 'data' not in configmap_spec or not configmap_spec['data']:
                print("No data found in configmap.")
                input("\nPress Enter to continue...")
                return

            print("\nConfigMap data:")
            print("-" * 50)
            for key, value in configmap_spec['data'].items():
                print(f"\n{key}:")
                try:
                    parsed_json = json.loads(value)
                    print(json.dumps(parsed_json, indent=2))
                except json.JSONDecodeError:
                    print(value)
            print("-" * 50)
            input("\nPress Enter to continue...")
            
        except KeyboardInterrupt:
            print("\nView cancelled by user.")
            return 
