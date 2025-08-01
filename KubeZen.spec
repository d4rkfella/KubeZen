# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

# --- Helper Functions for Dynamic Discovery ---

def get_kubezen_modules(subpackage: str) -> list[str]:
    """
    Dynamically discovers all modules in a KubeZen subpackage.
    This is used to automatically include all models and actions
    as hidden imports for PyInstaller.
    """
    modules = []
    package_dir = Path(SPECPATH) / "src" / "KubeZen" / subpackage
    for path in package_dir.glob("*.py"):
        if path.stem != "__init__":
            modules.append(f"KubeZen.{subpackage}.{path.stem}")
    return modules

# --- Main Configuration ---

# Determine the project root directory (where this spec file is located)
PROJECT_ROOT = SPECPATH

# Correct entry point for the application
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, 'src', 'KubeZen', 'main.py')

# Output directory for the build
DIST_PATH = os.path.join(PROJECT_ROOT, 'dist')

# Build directory
BUILD_PATH = os.path.join(PROJECT_ROOT, 'build')

# Name of the executable
APP_NAME = 'kubezen'

# --- Data and Binary Bundling ---

datas_to_bundle = []

# 1. Add the entire 'bin' directory.
bin_dir = Path(PROJECT_ROOT) / 'bin'
if bin_dir.is_dir():
    datas_to_bundle.append((str(bin_dir), 'bin'))
else:
    print(f"WARNING: 'bin' directory not found at {bin_dir}", file=sys.stderr)

# 2. Add the entire 'assets' directory.
assets_dir = Path(PROJECT_ROOT) / 'assets'
if assets_dir.is_dir():
    datas_to_bundle.append((str(assets_dir), 'assets'))
else:
    print(f"WARNING: 'assets' directory not found at {assets_dir}", file=sys.stderr)


# --- PyInstaller Analysis ---

# Discover all models and actions automatically
hidden_imports = get_kubezen_modules("models") + get_kubezen_modules("actions")
# Add other essential hidden imports
hidden_imports.extend([
    'click',
    'libtmux',
    'rich',
    'textual',
    'textual.widgets._tab_pane',
    'kubernetes_asyncio',
    'yaml',
    'typing_extensions',
    'shutil',
    # Add any other specific hidden imports your app needs
])


a = Analysis(
    [MAIN_SCRIPT],
    pathex=[os.path.join(PROJECT_ROOT, 'src')],  # Add 'src' to path
    binaries=[],
    datas=datas_to_bundle,
    hiddenimports=hidden_imports,
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
