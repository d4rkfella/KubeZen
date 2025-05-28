#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from .kube_base import KubeBase # Adjusted import
import sys
import base64
import json

class SecretManager(KubeBase):
    resource_type = "secrets"
    resource_name = "Secret"

    def __init__(self):
        super().__init__()

    def _get_resource_fzf_elements(self) -> List[dict]:
        return [
            {"fzf_bind_action": "alt-d:accept", "header_text": "Alt-D: Decode Secret"},
        ]

    def _get_resource_actions(self):
        """Provide secret-specific actions"""
        return {
            "alt-d": self._decode_secret
        }

    def _decode_secret(self, secret_name: str):
        """Decode and display secret data using KubectlClient."""
        subprocess.run(["clear"])
        print(f"Decoding secret '{secret_name}' in namespace '{self.current_namespace}'...")
        
        secret_spec = self.kubectl_client.get_resource_spec("secret", secret_name, self.current_namespace)

        if not secret_spec:
            input("\nPress Enter to continue...")
            return
        
        try:
            if 'data' not in secret_spec or not secret_spec['data']:
                print("No data found in secret.")
                input("\nPress Enter to continue...")
                return

            print("\nDecoded secret data:")
            print("-" * 50)
            for key, value in secret_spec['data'].items():
                print(f"\n{key}:")
                try:
                    decoded_value = base64.b64decode(value).decode('utf-8')
                    try:
                        parsed_json = json.loads(decoded_value)
                        print(json.dumps(parsed_json, indent=2))
                    except json.JSONDecodeError:
                        print(decoded_value)
                except Exception as e:
                    print(f"[Error decoding value: {str(e)}]")
            print("-" * 50)
            input("\nPress Enter to continue...")

        except KeyboardInterrupt:
            print("\nView cancelled by user.")
            return 