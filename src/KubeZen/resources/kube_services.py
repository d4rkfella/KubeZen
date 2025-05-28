#!/usr/bin/env python3
import subprocess
import json
import re
import sys
from typing import List, Tuple, Optional
from .kube_base import KubeBase
from .kube_port_forward import PortForwardManager

class ServiceManager(KubeBase):
    resource_type = "services"
    resource_name = "Service"

    def __init__(self):
        super().__init__()
        self.port_forward_manager = PortForwardManager(self)

    def _get_resource_fzf_elements(self) -> List[dict]:
        return [
            {"fzf_bind_action": "alt-p:accept", "header_text": "Alt-P: Port Forward"},
        ]

    def _get_resource_actions(self):
        """Provide service-specific actions"""
        return {
            "alt-p": lambda s: self.port_forward_manager.manage_port_forwards(selected_resource=("service", s))
        } 