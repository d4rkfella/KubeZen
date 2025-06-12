# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# Determine the project root directory (where this spec file is located)
PROJECT_ROOT = SPECPATH # Use SPECPATH provided by PyInstaller

# Path to the main script
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, 'src', 'KubeZen', 'cli.py')

# Output directory for the build
DIST_PATH = os.path.join(PROJECT_ROOT, 'dist')

# Build directory
BUILD_PATH = os.path.join(PROJECT_ROOT, 'build')

# Name of the executable
APP_NAME = 'kubezen'

# Directory where all static binaries are located
BIN_DIR = os.path.join(PROJECT_ROOT, 'bin')

# Directory where FZF Vim plugin files are stored
FZF_VIM_PLUGIN_DIR = os.path.join(PROJECT_ROOT, 'assets', 'fzf_vim_plugin')

# --- Helper function to check for binary existence ---
def check_binary(name, path):
    if not os.path.exists(path):
        print(f"WARNING: {name} not found at {path}. The build will likely fail or the app will be incomplete.", file=sys.stderr)
        return None
    return path

# Binaries to bundle (all from bin directory)
binaries_to_bundle = []

# 1. kubectl
kubectl_path = check_binary('kubectl', os.path.join(BIN_DIR, 'kubectl'))
if kubectl_path: binaries_to_bundle.append((kubectl_path, 'bin'))

# 2. fzf
fzf_path = check_binary('fzf', os.path.join(BIN_DIR, 'fzf'))
if fzf_path: binaries_to_bundle.append((fzf_path, 'bin'))

# 3. fzf-tmux script
fzf_tmux_path = check_binary('fzf-tmux', os.path.join(BIN_DIR, 'fzf-tmux'))
if fzf_tmux_path: binaries_to_bundle.append((fzf_tmux_path, 'bin'))

# 4. tmux
tmux_path = check_binary('tmux', os.path.join(BIN_DIR, 'tmux'))
if tmux_path: binaries_to_bundle.append((tmux_path, 'bin'))

# 5. vim
vim_path = check_binary('vim', os.path.join(BIN_DIR, 'vim'))
if vim_path: binaries_to_bundle.append((vim_path, 'bin'))

# Data files to bundle
data_files_to_bundle = []

# 1. app.vimrc
app_vimrc_path = os.path.join(PROJECT_ROOT, 'assets', 'runtime_config', 'app.vimrc')
if os.path.exists(app_vimrc_path):
    # Corrected destination to match config.py: assets/runtime_config/
    data_files_to_bundle.append((app_vimrc_path, os.path.join('assets', 'runtime_config')))
else:
    print(f"WARNING: app.vimrc not found at {app_vimrc_path}", file=sys.stderr)

# 2. FZF Vim plugin files
if os.path.exists(FZF_VIM_PLUGIN_DIR):
    for root, dirs, files in os.walk(FZF_VIM_PLUGIN_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            # Calculate relative path from FZF_VIM_PLUGIN_DIR to maintain structure
            rel_path_from_plugin_root = os.path.relpath(file_path, FZF_VIM_PLUGIN_DIR)
            # Corrected base destination directory in the bundle
            dest_dir = os.path.join('assets', 'fzf_vim_plugin', os.path.dirname(rel_path_from_plugin_root))
            data_files_to_bundle.append((file_path, dest_dir))
else:
    print(f"WARNING: FZF Vim plugin directory not found at {FZF_VIM_PLUGIN_DIR}", file=sys.stderr)

# 3. FZF Base plugin files (junegunn/fzf's Vim plugin files)
FZF_BASE_PLUGIN_DIR = os.path.join(PROJECT_ROOT, 'assets', 'fzf_base_plugin')
if os.path.exists(FZF_BASE_PLUGIN_DIR):
    for root, dirs, files in os.walk(FZF_BASE_PLUGIN_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            # Calculate relative path from FZF_BASE_PLUGIN_DIR to maintain structure
            rel_path_from_plugin_root = os.path.relpath(file_path, FZF_BASE_PLUGIN_DIR)
            # Corrected base destination directory in the bundle
            dest_dir = os.path.join('assets', 'fzf_base_plugin', os.path.dirname(rel_path_from_plugin_root))
            data_files_to_bundle.append((file_path, dest_dir))
else:
    print(f"WARNING: FZF Base plugin directory not found at {FZF_BASE_PLUGIN_DIR}", file=sys.stderr)

# 4. terminfo files
TERMINFO_DIR = os.path.join(PROJECT_ROOT, 'resources', 'terminfo')
if os.path.exists(TERMINFO_DIR):
    for root, dirs, files in os.walk(TERMINFO_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, TERMINFO_DIR)
            dest_dir = os.path.join('resources', 'terminfo', os.path.dirname(rel_path))
            data_files_to_bundle.append((file_path, dest_dir))
else:
    print(f"WARNING: terminfo directory not found at {TERMINFO_DIR}", file=sys.stderr)


# --- PyInstaller Analysis ---
a = Analysis(
    [MAIN_SCRIPT],
    pathex=[os.path.join(PROJECT_ROOT, 'src')],  # To find KubeZen module
    binaries=binaries_to_bundle,
    datas=data_files_to_bundle,
    hiddenimports=[
        'click',
        'libtmux',
        'KubeZen.config',
        'KubeZen.resources',
        'KubeZen.resources.kube_base',
        'KubeZen.resources.kube_port_forward',
        'KubeZen.resources.kube_namespaces',
        'KubeZen.resources.kube_pods',
        'KubeZen.resources.kube_pvcs',
        'KubeZen.resources.kube_services',
        'KubeZen.resources.kube_edit',
        'KubeZen.resources.kube_statefulsets',
        'KubeZen.resources.kube_deployments',
        'KubeZen.resources.kube_daemonsets',
        'KubeZen.resources.kube_configmaps',
        'KubeZen.resources.kube_secrets',
        'KubeZen.resources.kube_logs',
        'shutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name=APP_NAME,
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=True,  # True for CLI application
          disable_windowed_traceback=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_file=None
)
