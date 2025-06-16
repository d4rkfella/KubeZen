# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# Determine the project root directory (where this spec file is located)
PROJECT_ROOT = SPECPATH # Use SPECPATH provided by PyInstaller

# Path to the main script
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, 'run_kubezen.py')

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

# --- Data and Binary Bundling ---
# We bundle the entire 'bin' and 'assets' directories to ensure all required
# files are included and their structure is maintained.

datas_to_bundle = []

# 1. Add the entire 'bin' directory.
if os.path.isdir(BIN_DIR):
    datas_to_bundle.append((BIN_DIR, 'bin'))
else:
    print(f"WARNING: 'bin' directory not found at {BIN_DIR}", file=sys.stderr)

# 2. Add the entire 'assets' directory.
assets_dir = os.path.join(PROJECT_ROOT, 'assets')
if os.path.isdir(assets_dir):
    datas_to_bundle.append((assets_dir, 'assets'))
else:
    print(f"WARNING: 'assets' directory not found at {assets_dir}", file=sys.stderr)

# 3. Add any other resource directories here if needed in the future.
# For example, if you still have a 'resources/terminfo'
terminfo_dir = os.path.join(PROJECT_ROOT, 'resources', 'terminfo')
if os.path.isdir(terminfo_dir):
    datas_to_bundle.append((terminfo_dir, os.path.join('resources', 'terminfo')))

# 4. Add the application's CSS file.
#    The destination is 'KubeZen' so it's placed alongside the app's module.
app_css_path = os.path.join(PROJECT_ROOT, 'src', 'KubeZen', 'app.css')
if os.path.isfile(app_css_path):
    datas_to_bundle.append((app_css_path, 'KubeZen'))
else:
    print(f"WARNING: 'app.css' not found at {app_css_path}", file=sys.stderr)

# --- PyInstaller Analysis ---
a = Analysis(
    [MAIN_SCRIPT],
    pathex=[os.path.join(PROJECT_ROOT, 'src')], # Add 'src' to path
    binaries=[],  # We now handle binaries as data files to preserve structure
    datas=datas_to_bundle,
    hiddenimports=[
        'click',
        'libtmux',
        'rich',
        'textual',
        'requests',
        'kubernetes',
        'kubernetes_asyncio',
        'yaml',
        'aiofiles',
        'typing_extensions',
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
          strip=True,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=True,  # True for CLI application
          disable_windowed_traceback=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_file=None
)
