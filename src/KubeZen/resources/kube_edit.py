#!/usr/bin/env python3
import subprocess
import sys
import libtmux
from typing import Optional
import os
from .kube_base import KubeBase

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        project_root_for_dev = os.path.join(os.getcwd(), "KubeZen") 

        if relative_path.startswith("bin/"):
            return relative_path.split("/")[1]
        
        if relative_path == "config/app.vimrc":
            dev_vimrc_path = os.path.join(project_root_for_dev, "assets", "runtime_config", "app.vimrc")
            if os.path.exists(dev_vimrc_path):
                return dev_vimrc_path
            else:
                print(f"Development mode: Could not find project app.vimrc at {dev_vimrc_path}. Falling back to user ~/.vimrc", file=sys.stderr)
                return os.path.expanduser("~/.vimrc")

        if relative_path == "config/fzf_vim_plugin/plugin/fzf.vim":
            user_fzf_vim_plugin_file = os.path.expanduser("~/.vim/pack/plugins/start/fzf.vim/plugin/fzf.vim")
            if os.path.exists(user_fzf_vim_plugin_file):
                return user_fzf_vim_plugin_file
            user_fzf_vim_plugin_file = os.path.expanduser("~/.vim/plugin/fzf.vim")
            if os.path.exists(user_fzf_vim_plugin_file):
                return user_fzf_vim_plugin_file
            project_fzf_plugin = os.path.join(project_root_for_dev, "assets", "fzf_vim_plugin", "plugin", "fzf.vim")
            if os.path.exists(project_fzf_plugin):
                 return project_fzf_plugin
            print(f"Development mode: Could not find user's or project's fzf.vim plugin file.", file=sys.stderr)
            return None
        
        if relative_path == "config/fzf_vim_plugin/fzf":
            user_fzf_runtime_dir = os.path.expanduser("~/.fzf")
            if os.path.exists(user_fzf_runtime_dir):
                return user_fzf_runtime_dir
            project_fzf_runtime = os.path.join(project_root_for_dev, "assets", "fzf_vim_plugin", "fzf")
            if os.path.exists(project_fzf_runtime):
                return project_fzf_runtime
            print(f"Development mode: Could not find user's or project's fzf runtime directory.", file=sys.stderr)
            return None

        return os.path.join(project_root_for_dev, relative_path) 

    return os.path.join(base_path, relative_path)

class KubeEdit:
    def __init__(self, base: KubeBase):
        self.base = base

    def edit_in_tmux(self, resource_name: str, resource_type: str, namespace: Optional[str], title: str = None):
        """Edit a resource in tmux using kubectl edit."""
        if title is None:
            title = f"Edit: {resource_name}"

        try:
            with libtmux.Server() as server:
                session_name = f"edit-{resource_type}-{resource_name.lower().replace(' ', '-')}"
                if namespace:
                    session_name += f"-{namespace}"

                kubectl_exe = get_resource_path("bin/kubectl")
                kubectl_cmd_parts = [kubectl_exe, "edit", resource_type, resource_name]
                if namespace:
                    kubectl_cmd_parts.extend(["-n", namespace])
                
                window_command = " ".join(kubectl_cmd_parts)
                
                session_environment = {}
                vim_exe = get_resource_path("bin/vim")
                vimrc_path = get_resource_path("config/app.vimrc")

                if not vim_exe or not os.path.exists(vim_exe if sys.platform != "win32" else vim_exe + ".exe"):
                    print(f"Error: Vim executable not found at '{vim_exe}'. Cannot proceed with edit.", file=sys.stderr)
                    input("\nPress Enter to continue...")
                    return
                if not vimrc_path or not os.path.exists(vimrc_path):
                    print(f"Warning: Vimrc file not found at '{vimrc_path}'. Vim will use default settings.", file=sys.stderr)
                
                session_environment['EDITOR'] = f'{vim_exe} -u {vimrc_path}' if vimrc_path and os.path.exists(vimrc_path) else vim_exe

                if 'KUBECONFIG' in os.environ:
                    session_environment['KUBECONFIG'] = os.environ['KUBECONFIG']

                session = server.new_session(
                    session_name=session_name,
                    window_name=title,
                    start_directory=None, 
                    attach=False,
                    window_command=window_command,
                    environment=session_environment 
                )

                session.set_option('status-left', '#[fg=green]#H #[fg=black]• #[fg=blue,bold]📝') 
                session.set_option('status-right', '#[fg=green]#(cut -d " " -f 1 /proc/loadavg)#[default] #[fg=blue]%H:%M#[default] #[fg=yellow]🚪 :wq to save and apply#[default]')

                session.attach_session()

                print(f"\nResource is being shown in editor.")
                print("\nSearch and Navigation (standard Vim/editor commands):")
                print("- Regular search: / (forward) or ? (backward)")
                print("- Next match: n (forward) or N (backward)")
                print("\nExit:")
                print("- Type :wq to save changes and apply to cluster")
                print("- Type :q! to discard changes and exit")
                input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            print(f"Error during kubectl edit setup: {e.stderr.strip() if e.stderr else e}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except libtmux.exc.LibTmuxException as e:
            print(f"Error interacting with tmux: {e}. Your tmux server might be unstable.", file=sys.stderr) 
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            input("\nPress Enter to continue...")
            # return self.base.handle_keyboard_interrupt() # This would require self.base to be set
