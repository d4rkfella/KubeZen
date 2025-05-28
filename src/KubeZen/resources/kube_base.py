#!/usr/bin/env python3
import subprocess
import sys
import os
import stat
from typing import List, Optional, Tuple, Union
import libtmux
import tempfile
import json
from ..kubectl_client import KubectlClient # Adjusted path
from .kube_namespaces import NamespaceManager # Path likely okay if in same dir

FZF_COLORS = {
    "fg": "#d0d0d0",
    "bg": "#1b1b1b",
    "hl": "#00afff",
    "fg+": "#ffffff",
    "bg+": "#005f87",
    "hl+": "#00afff",
    "info": "#87ffaf",
    "prompt": "#ff5f00",
    "pointer": "#af00ff"
}

class KubeBase:
    resource_type = ""
    resource_name = ""

    def __init__(self):
        self.current_namespace = None
        self._edit_manager = None
        self.kubectl_client = KubectlClient()

    def _get_edit_manager(self):
        if self._edit_manager is None:
            from .kube_edit import KubeEdit # Adjusted path
            self._edit_manager = KubeEdit(self)
        return self._edit_manager

    def handle_keyboard_interrupt(self):
        print("\nOperation cancelled by user.")
        input("\nPress Enter to continue...")
        return "esc", None

    def _get_fzf_style(self):
        style = [
            "--history-size=1000",
            "--layout=reverse",
            "--border=rounded",
            "--margin=1,2"
        ]
        for k, v in FZF_COLORS.items():
            style += ["--color", f"{k}:{v}"]
        return style

    def _get_common_fzf_elements(self, preview_command_template: Optional[str] = None):
        current_ns_part = f" -n {self.current_namespace}" if self.current_namespace else ""
        if self.resource_type in ["namespaces", "nodes", "persistentvolumes"]:
            current_ns_part = ""
        
        current_resource_type = self.resource_type or ""

        elements = [
            {
                "key": "alt-d", 
                "fzf_bind_action": f"alt-d:change-preview(kubectl describe {current_resource_type}/{{{{1}}}}{current_ns_part})+change-preview-window(hidden|right:60%:wrap)",
                "header_text": "Alt-D: Describe", 
                "type": "fzf_feature_preview",
                "requires_resource_type_for_preview": True, 
                "requires_namespace_for_preview": bool(self.current_namespace) and self.resource_type not in ["namespaces", "nodes", "persistentvolumes"]
            },
            {
                "key": "alt-w", 
                "fzf_bind_action": f"alt-w:change-preview(kubectl get {current_resource_type}/{{{{1}}}}{current_ns_part} -o wide)+change-preview-window(hidden|right:90%:wrap)",
                "header_text": "Alt-W: Wide", 
                "type": "fzf_feature_preview",
                "requires_resource_type_for_preview": True, 
                "requires_namespace_for_preview": bool(self.current_namespace) and self.resource_type not in ["namespaces", "nodes", "persistentvolumes"]
            },
            {
                "key": "alt-v", 
                "fzf_bind_action": f"alt-v:change-preview(kubectl get {current_resource_type}/{{{{1}}}}{current_ns_part} -o yaml)+change-preview-window(hidden|right:60%:wrap)",
                "header_text": "Alt-V: View YAML",
                "type": "fzf_feature_preview",
                "requires_resource_type_for_preview": True, 
                "requires_namespace_for_preview": bool(self.current_namespace) and self.resource_type not in ["namespaces", "nodes", "persistentvolumes"]
            },
            {
                "key": "alt-x", "fzf_bind_action": "alt-x:accept", "python_action_key": "alt-x",
                "header_text": "Alt-X: Delete", "type": "common_action", "is_expect_key": True
            },
            {
                "key": "alt-e", "fzf_bind_action": "alt-e:accept", "python_action_key": "alt-e",
                "header_text": "Alt-E: Edit", "type": "common_action", "is_expect_key": True
            },
            {
                "key": "enter", "fzf_bind_action": "enter:accept", "python_action_key": "enter",
                "header_text": "Enter: Select", "type": "common_action", "is_expect_key": True 
            },
            {
                "key": "ctrl-s", "fzf_bind_action": "ctrl-s:toggle-sort",
                "header_text": "Ctrl-S: Sort", "type": "fzf_feature_static"
            }
        ]
        return elements

    def _get_common_actions(self):
        return {
            "alt-e": lambda r: self._get_edit_manager().edit_in_tmux(
                resource_name=r, 
                resource_type=self.resource_type, 
                namespace=None if self.resource_type == "namespaces" else self.current_namespace
            ),
            "alt-x": lambda r: self._confirm_delete_resource(r),
        }

    def _get_resource_actions(self):
        return {}
    
    def _get_resource_fzf_elements(self) -> List[dict]:
        """
        Returns a list of dictionaries defining resource-specific fzf elements.
        Each dictionary should have at least 'fzf_bind_action' (e.g., "alt-c:accept")
        and 'header_text' (e.g., "Alt-C: Exec").
        This method should be overridden by subclasses.
        """
        return []

    def _handle_action(self, key: str, resource: str, namespace: Optional[str] = None):
        specific_actions = self._get_resource_actions()
        common_actions = self._get_common_actions()

        if key in specific_actions:
            try:
                specific_actions[key](resource, namespace)
            except TypeError:
                try:
                    specific_actions[key](resource)
                except Exception as e:
                    print(f"Error executing action '{key}' for '{resource}': {e}", file=sys.stderr)
                    input("\nPress Enter to continue...")
        elif key in common_actions:
            common_actions[key](resource)
        elif key == "enter":
            self._default_view(resource, namespace=namespace)

    def _confirm_delete_resource(self, resource: str, namespace: Optional[str] = None):
        """Prompt user for confirmation before deleting a resource."""
        print("\n")
        
        is_namespace_resource = self.resource_type == "namespaces"
        
        prompt_namespace_segment = ""
        effective_namespace = namespace if namespace is not None else self.current_namespace

        if not is_namespace_resource and effective_namespace:
            prompt_namespace_segment = f" in namespace '{effective_namespace}'"
            
        resource_display_name = self.resource_name

        try:
            confirm = input(f"Are you sure you want to delete {resource_display_name} '{resource}'{prompt_namespace_segment}? (y/N): ")
            if confirm.lower() == 'y':
                print(f"Deleting {resource_display_name} {resource}...")
                success, message = self.kubectl_client.delete_resource(
                    self.resource_type, resource, effective_namespace
                )
                print(message)
            else:
                print("Deletion cancelled.")
        except KeyboardInterrupt:
            print("\nDeletion cancelled by user.")
        finally:
            input("\nPress Enter to continue...")

    def _get_default_resource_preview_command(self):
        if self.resource_type and self.resource_type != "namespaces":
            return f"kubectl get {self.resource_type}/{{1}} -n {self.current_namespace} -o yaml"
        return None

    def run_fzf(
        self,
        items: List[str],
        title: str,
        extra_header: Optional[str] = None,
        extra_bindings: Optional[List[str]] = None,
        include_common_elements: Union[bool, List[str]] = True,
        preview_command_template: Optional[str] = None,
        preview_window_settings: str = "right:50%:wrap",
        multi_select: bool = False,
        default_select_first: bool = False,
        sort_items: bool = True
    ) -> Union[Tuple[str, str], str, List[str], None]:
        
        fzf_command = ["fzf"]
        fzf_command.extend(self._get_fzf_style())
        
        fzf_bindings_args: List[str] = []
        active_header_snippets: List[str] = []
        
        # Initialize active_expect_keys with "esc" as it's always handled for exiting fzf
        active_expect_keys = {"esc"} 

        # Process common elements if requested
        common_fzf_elements_to_use = []
        if isinstance(include_common_elements, bool) and include_common_elements:
            common_fzf_elements_to_use = self._get_common_fzf_elements(preview_command_template)
        elif isinstance(include_common_elements, list):
            all_common = self._get_common_fzf_elements(preview_command_template)
            common_fzf_elements_to_use = [el for el in all_common if el['key'] in include_common_elements]

        for element in common_fzf_elements_to_use:
            if element['type'] == 'preview_change' and \
               (self.resource_type is None or \
                (element.get('requires_namespace_for_preview', False) and self.current_namespace is None) or \
                (element.get('requires_resource_type_for_preview', False) and self.resource_type is None)
               ):
                continue

            fzf_bindings_args.extend(["--bind", element['fzf_bind_action']])
            active_header_snippets.append(element['header_text'])
            
            action_part = element['fzf_bind_action'].split(':')[-1]
            key_part = element['fzf_bind_action'].split(':')[0]

            if action_part == "accept" or element.get('is_expect_key', False):
                active_expect_keys.add(key_part)

        # Process extra_bindings provided by the caller
        if extra_bindings:
            fzf_bindings_args.extend(extra_bindings)
            for i in range(0, len(extra_bindings), 2): # Bindings are like ["--bind", "key:action"]
                if i + 1 < len(extra_bindings) and extra_bindings[i] == "--bind":
                    binding_arg = extra_bindings[i+1] # This is "key:action"
                    key_part, *action_parts = binding_arg.split(':', 1)
                    action_part_str = action_parts[0] if action_parts else ""
                    if action_part_str == "accept":
                        active_expect_keys.add(key_part)
        
        # Construct the final header
        header_lines = [title]
        
        # Common keybindings line (including Esc/Ctrl-C)
        common_bindings_header_parts = [snippet for snippet in active_header_snippets]
        if "esc" in active_expect_keys or "ctrl-c" in active_expect_keys : # We always expect esc
             # Check if a common element already provides text for 'esc'
            has_esc_header = any("Esc:" in h for h in common_bindings_header_parts)
            if not has_esc_header:
                 common_bindings_header_parts.append("Esc/Ctrl-C: Back/Exit")
        
        if common_bindings_header_parts:
            header_lines.append(" | ".join(common_bindings_header_parts))

        # Manager-specific header (if provided and different from already added common parts)
        if extra_header:
            # Avoid duplicating header info if extra_header is already part of common_bindings_header_parts
            is_extra_header_redundant = any(extra_header in common_part for common_part in common_bindings_header_parts)
            if not is_extra_header_redundant:
                if common_bindings_header_parts: # Add separator only if common bindings were present
                    header_lines.append("-" * 60) 
                header_lines.append(extra_header)
        
        header_lines.append("=" * 60) # Separator for list items, repeated
        fzf_command.extend(["--header", "\n".join(header_lines)])

        # Add bindings to fzf command
        fzf_command.extend(fzf_bindings_args)

        # Build the --expect argument for fzf
        expect_arg = ",".join(sorted(list(active_expect_keys))) 
        if expect_arg:
            fzf_command.extend(["--expect", expect_arg])

        if multi_select:
            fzf_command.append("-m")
        
        if default_select_first and items:
             fzf_command.extend(["--query", items[0], "--select-1", "--exit-0"])

        # ---- START DEBUG ----
        # print(f"DEBUG run_fzf: items before Popen: {repr(items)}", file=sys.stderr) # Keep this commented unless deep debugging items
        # print(f"DEBUG run_fzf: fzf_command before Popen: {fzf_command}", file=sys.stderr) # Keep this commented unless deep debugging command
        # ---- END DEBUG ----

        # Preview settings
        # This section is for a *default* hover preview if a template is provided directly.
        # It is distinct from the on-demand preview changes bound to keys like Alt-D/W/V.
        if preview_command_template:
            fzf_command.extend(["--preview", preview_command_template])
            fzf_command.extend(["--preview-window", preview_window_settings])

        if sort_items:
            pass # fzf sorts by default
        else:
            fzf_command.append("--no-sort")

        try:
            process = subprocess.Popen(fzf_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            stdout, _ = process.communicate(input="\n".join(items))
            
            return self.process_fzf_output(process.returncode, stdout.strip(), expect_arg, multi_select)

        except FileNotFoundError:
            print("Error: fzf command not found. Please ensure fzf is installed and in your PATH.", file=sys.stderr)
            return None
        except Exception as e:
            print(f"An unexpected error occurred with fzf: {e}", file=sys.stderr)
            return None

    def process_fzf_output(self, return_code: int, stdout: str, expect_keys_str: str, multi_select: bool = False) -> Union[Tuple[str, str], str, List[str], None]:
        """Processes the output from the fzf command.

        Args:
            return_code: The return code from the fzf subprocess.
            stdout: The stdout from the fzf subprocess.
            expect_keys_str: Comma-separated string of keys fzf was told to expect.
            multi_select: Whether fzf was run in multi-select mode.

        Returns:
            - If a key from expect_keys_str (other than default enter) is pressed: (key, selected_item)
            - If Enter is pressed (and not in expect_keys_str or no other key pressed): selected_item (or list of items if multi_select)
            - If Esc is pressed or fzf exits otherwise (return code 1, 130): None (or (esc, None) if esc was an expect key)
        """
        # ---- START DEBUG ----
        # print(f"DEBUG process_fzf_output: return_code={return_code}, stdout={repr(stdout)}, expect_keys_str='{expect_keys_str}', multi_select={multi_select}", file=sys.stderr)
        lines = stdout.strip().split('\n')
        # print(f"DEBUG process_fzf_output: lines={lines}", file=sys.stderr)
        # ---- END DEBUG ----
        
        if return_code == 0: # Standard Enter press, or --select-1 --exit-0 scenario
            if not lines or not lines[0]: # Empty output
                return None
            # If expect_keys_str is empty or only has 'esc', this is a simple selection.
            # Also, if 'enter' is an expected key and it's the first line, it's a specific 'enter' action.
            if not expect_keys_str or expect_keys_str == "esc" or (lines[0] == "enter" and "enter" in expect_keys_str.split(',')):
                if multi_select:
                    # If 'enter' was expected and is the first line, the rest are selections
                    return lines[1:] if lines[0] == "enter" and len(lines) > 1 else lines
                else:
                    # If 'enter' was expected, return it with the selected item
                    return ("enter", lines[1]) if lines[0] == "enter" and len(lines) > 1 else lines[0]
            # If other keys were expected, and the first line is one of them:
            elif lines[0] in expect_keys_str.split(','):
                return lines[0], (lines[1] if len(lines) > 1 else None)
            else: # Default selection without a specific expected key match (should be rare with expect_keys)
                return lines[0] if not multi_select else lines

        elif return_code == 1: # Default fzf exit (usually Esc), or a key from --expect was pressed
            if not lines or not lines[0]: # Can happen if Esc is pressed with no input/selection
                return ("esc", None) # Consistent return for Esc
            
            pressed_key = lines[0]
            selected_value = lines[1] if len(lines) > 1 else None
            
            if pressed_key in expect_keys_str.split(','):
                return pressed_key, selected_value
            else: # If key wasn't in expect_keys_str, it implies Esc or similar abort
                return ("esc", None) 

        elif return_code == 130: # Ctrl+C
            return ("esc", None) # Treat Ctrl+C same as Esc for our purposes
        
        # Other return codes or unexpected scenarios
        # print(f"fzf exited with code {return_code} and output: {stdout}", file=sys.stderr)
        return None

    def navigate(self, resources: Optional[List[str]] = None, title: Optional[str] = None):
        while True:
            if self.current_namespace is None:
                # Select namespace first
                ns_manager = NamespaceManager(self)
                selected_namespace_tuple = ns_manager.select_resource(
                    include_common_elements=["edit", "delete", "alt-x"]
                )
                # ---- START DEBUG ----
                # print(f"DEBUG navigate: selected_namespace_tuple from ns_manager.select_resource: {selected_namespace_tuple}", file=sys.stderr)
                # ---- END DEBUG ----

                if selected_namespace_tuple is None: 
                    print("Exiting.")
                    return

                action, selected_ns_name = selected_namespace_tuple
                
                if action == "esc": # Should be handled by select_resource returning None, but as a safeguard
                    print("Exiting.")
                    return
                
                if selected_ns_name:
                    self.current_namespace = selected_ns_name
                    print(f"Switched to namespace: {self.current_namespace}")
                    resources = None # Ensure we fetch new resources for the selected namespace
                    title = None
                else: # No namespace selected, or an action was taken that didn't set a namespace
                    # This could happen if 'edit' or 'delete' was chosen for a namespace.
                    # The loop will restart, and if current_namespace is still None, it will re-prompt.
                    # If an action like delete occurred, the list will refresh.
                    continue # Restart the loop to show namespace selection again or exit

            # If a resource list is provided directly (e.g., from a previous action like undo)
            if resources:
                current_title = title if title else f"{self.resource_type} in {self.current_namespace}"
                # When displaying a pre-fetched list, we might not want common describe/wide/view previews
                # if they don't make sense or if the list is already specific enough.
                # However, basic actions like edit/delete might still be relevant from common elements.
                
                resource_elements = self._get_resource_fzf_elements()
                manager_extra_bindings = []
                manager_header_parts = []
                for el in resource_elements:
                    manager_extra_bindings.extend(["--bind", el['fzf_bind_action']])
                    manager_header_parts.append(el['header_text'])
                manager_extra_header = " | ".join(manager_header_parts) if manager_header_parts else None
                
                result = self.run_fzf(
                    resources, 
                    current_title,
                    extra_header=manager_extra_header,
                    extra_bindings=manager_extra_bindings,
                    # include_common_elements can be True or a specific list if needed
                    include_common_elements=True # Or a list: ["edit", "delete", "alt-x", "logs", "exec", "port-forward"]
                )
                resources = None # Clear after displaying once
                title = None
            else:
                # Default: Fetch and display resources for the current type and namespace
                refreshed_items = self._refresh_resources(namespace=self.current_namespace)
                if refreshed_items is None: # Error occurred during refresh
                    print(f"Failed to refresh {self.resource_type}. Returning to namespace selection.")
                    self.current_namespace = None # Force re-selection of namespace
                    input("\nPress Enter to continue...")
                    continue
                
                resource_elements = self._get_resource_fzf_elements()
                manager_extra_bindings = []
                manager_header_parts = []
                for el in resource_elements:
                    manager_extra_bindings.extend(["--bind", el['fzf_bind_action']])
                    manager_header_parts.append(el['header_text'])
                manager_extra_header = " | ".join(manager_header_parts) if manager_header_parts else None

                result = self.run_fzf(
                    refreshed_items, 
                    f"{self.resource_name}s in {self.current_namespace}",
                    extra_header=manager_extra_header,
                    extra_bindings=manager_extra_bindings,
                    include_common_elements=True
                )

            if result is None:
                print("Exiting or error in fzf.") # Should be rare if esc is handled
                return

            action, selected_item = result

            if action == "esc":
                if self.current_namespace is not None:
                    print(f"Returning to namespace selection from {self.resource_type} list.")
                    self.current_namespace = None
                    # We don't set self.resource_type to None here, main loop handles it
                    continue # Go back to namespace selection
                else:
                    print("Exiting from namespace selection (Esc).") # Should be caught by ns_manager returning None
                    return
            
            self._handle_action(action, selected_item, self.current_namespace)

    def _refresh_resources(self, namespace=None):
        return self.kubectl_client.get_resources(self.resource_type, namespace)

    def _default_view(self, resource_name: str, namespace: Optional[str] = None):
        """Default action when Enter is pressed on a resource. Typically shows details or navigates deeper."""
        # This should be overridden by subclasses if they have a default Enter action.
        # For KubeBase itself, we can just describe the resource.
        print(f"Describing {self.resource_name} '{resource_name}" + (f" in namespace '{namespace}'" if namespace else "") + "...")
        effective_namespace = namespace if namespace is not None else self.current_namespace
        if self.resource_type == "namespaces": # Namespaces are not namespaced
            effective_namespace = None
        
        spec_data = self.kubectl_client.get_resource_spec(self.resource_type, resource_name, effective_namespace)
        if spec_data is None: # Error occurred or no spec found
            # The get_resource_spec method in KubectlClient already prints the specific error to stderr
            print(f"Could not retrieve details for {self.resource_type} '{resource_name}'. Check previous error messages.", file=sys.stderr)
        else:
            # Pretty print JSON
            print(json.dumps(spec_data, indent=2))
        input("\nPress Enter to continue...") 