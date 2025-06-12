from __future__ import annotations
import os
import sys
import shutil
import secrets
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, ClassVar
import json

from KubeZen.core.exceptions import ConfigurationError, BinaryNotFoundError

# --- Constants ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_EXPORT_FILENAME = "app_config.json"


# --- Helper Classes ---
@dataclass
class Resource:
    """Represents a required resource in the system."""

    path: str
    is_executable: bool = False
    is_directory: bool = False
    is_optional: bool = False


@dataclass
class ConfigValue:
    """Represents a configuration value with its environment variable and default."""

    env_var: str
    default: Any
    type_converter: Optional[type] = None


@dataclass
class KubeZenConfig:
    """Type-safe configuration for KubeZen."""

    # Core settings
    kubezen_session_name: str
    kubezen_initial_window_name: str
    kubezen_socket_name: str
    kubezen_initial_context: str
    kube_config_path_override: str
    fzf_api_key: str
    debug_mode: bool
    log_level: str
    session_temp_dir: Path
    kubernetes_retry_delay_seconds: float
    k8s_watch_timeout_seconds: int
    fzf_api_timeout_seconds: float
    log_retention_count: int

    # Derived paths (computed during initialization)
    tmux_socket_path: Path = field(init=False)
    permanent_log_dir: Path = field(init=False)
    temp_log_dir: Path = field(init=False)
    temp_fzf_dir: Path = field(init=False)
    current_kube_context_name: str = field(init=False)
    kube_config_path: str = field(init=False)

    # Resource paths (resolved during initialization)
    python_executable_path: Path = field(init=False)
    kubectl_path: Path = field(init=False)
    tmux_path: Path = field(init=False)
    fzf_path: Path = field(init=False)
    fzf_tmux_script_path: Path = field(init=False)
    core_ui_runner_script_path: Path = field(init=False)
    kubezen_tmux_config_path: Path = field(init=False)
    mouse_swipe_plugin_script_path: Path = field(init=False)
    fzf_item_reader_script_path: Path = field(init=False)
    pvc_file_browser_script_path: Path = field(init=False)
    less_path: Optional[Path] = field(init=False)
    vim_path: Optional[Path] = field(init=False)

    # Configuration schema
    CONFIG_VALUES: ClassVar[Dict[str, ConfigValue]] = {
        "kubezen_session_name": ConfigValue("KUBEZEN_SESSION_NAME", "kubezen"),
        "kubezen_initial_window_name": ConfigValue("KUBEZEN_INITIAL_WINDOW_NAME", "main"),
        "kubezen_socket_name": ConfigValue("KUBEZEN_SOCKET_NAME", "kubezen_socket"),
        "kubezen_initial_context": ConfigValue("KUBEZEN_INITIAL_CONTEXT", ""),
        "kube_config_path_override": ConfigValue("KUBE_CONFIG_PATH_OVERRIDE", ""),
        "fzf_api_key": ConfigValue("KUBEZEN_FZF_API_KEY", secrets.token_hex(16)),
        "debug_mode": ConfigValue("KUBEZEN_DEBUG_MODE", False, bool),
        "log_level": ConfigValue("KUBEZEN_LOG_LEVEL", "INFO"),
        "session_temp_dir": ConfigValue("KUBEZEN_SESSION_TEMP_DIR", ""),
        "kubernetes_retry_delay_seconds": ConfigValue(
            "KUBEZEN_KUBERNETES_RETRY_DELAY_SECONDS", 0.2, float
        ),
        "k8s_watch_timeout_seconds": ConfigValue("KUBEZEN_K8S_WATCH_TIMEOUT_SECONDS", 300, int),
        "fzf_api_timeout_seconds": ConfigValue("KUBEZEN_FZF_API_TIMEOUT_SECONDS", 2.0, float),
        "log_retention_count": ConfigValue("KUBEZEN_LOG_RETENTION_COUNT", 50, int),
    }

    REQUIRED_RESOURCES: ClassVar[Dict[str, Resource]] = {
        "python_executable": Resource(sys.executable, is_executable=True),
        "kubectl": Resource("kubectl", is_executable=True),
        "fzf": Resource("fzf", is_executable=True),
        "tmux": Resource("tmux", is_executable=True),
        "less": Resource("less", is_executable=True, is_optional=True),
        "vim": Resource("vim", is_executable=True, is_optional=True),
        "fzf_tmux_script": Resource("bin/fzf-tmux", is_executable=True),
        "core_ui_runner_script": Resource("src/KubeZen/core_ui_runner.py"),
        "kubezen_tmux_config": Resource("assets/tmux/kubezen.tmux.conf"),
        "mouse_swipe_plugin_script": Resource(
            "assets/tmux/tmux_plugins/tmux-mouse-swipe/mouse-swipe.tmux"
        ),
        "fzf_item_reader_script": Resource("bin/fzf_item_reader.py", is_executable=True),
        "pvc_file_browser_script": Resource("bin/pvc_file_browser.sh", is_executable=True),
    }

    @classmethod
    def from_env(cls) -> "KubeZenConfig":
        """Creates a KubeZenConfig instance from environment variables."""
        config_dict = {}
        for key, config_value in cls.CONFIG_VALUES.items():
            env_value = os.environ.get(config_value.env_var)
            if env_value is not None:
                if config_value.type_converter:
                    value = config_value.type_converter(env_value)
                else:
                    value = env_value
            else:
                value = config_value.default
            config_dict[key] = value

        instance = cls(**config_dict)
        instance._initialize_permanent_dirs()
        instance._initialize_temp_dirs()
        instance._resolve_resource_paths()
        instance._set_derived_paths()
        return instance

    def _initialize_permanent_dirs(self) -> None:
        """Creates permanent directories for logs and other persistent data."""
        self.permanent_log_dir = Path.home() / ".kubezen" / "logs"
        self.permanent_log_dir.mkdir(parents=True, exist_ok=True)

    def _initialize_temp_dirs(self) -> None:
        """Creates all necessary temporary directories for the session."""
        if self.session_temp_dir and Path(self.session_temp_dir).is_dir():
            self.session_temp_dir = Path(self.session_temp_dir)
        else:
            new_temp_dir = Path(f"/tmp/kubezen_session_{os.getpid()}_{secrets.token_hex(4)}")
            new_temp_dir.mkdir(parents=True, exist_ok=True)
            self.session_temp_dir = new_temp_dir

        os.environ["KUBEZEN_SESSION_TEMP_DIR"] = str(self.session_temp_dir)

        self.temp_log_dir = self.session_temp_dir / "logs"
        self.temp_fzf_dir = self.session_temp_dir / "fzf"

        for d in [self.temp_log_dir, self.temp_fzf_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _resolve_resource_paths(self) -> None:
        """
        Resolves paths for all required resources with a specific priority:
        1. For executables, check the workspace bin folder first.
        2. Check for the resource relative to the workspace root.
        3. For executables, fall back to the system's PATH.
        Also handles resolution when running in a PyInstaller bundle.
        """
        is_packaged = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

        if is_packaged:
            # mypy doesn't know about _MEIPASS, so we ignore the type error
            workspace_root = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        else:
            workspace_root = PROJECT_ROOT

        bin_dir = workspace_root / "bin"

        for name, resource in self.REQUIRED_RESOURCES.items():
            resolved_path: Optional[Path] = None
            source: Optional[str] = None

            # 1. Handle special case for python_executable
            if name == "python_executable":
                resolved_path = Path(resource.path)
                source = "environment"

            # 2. Check workspace bin for executables
            if resource.is_executable and not resolved_path:
                if bin_dir.is_dir():
                    potential_path = bin_dir / Path(resource.path).name
                    if potential_path.is_file():
                        resolved_path = potential_path
                        source = "workspace bin"

            # 3. Check relative to workspace root
            if not resolved_path:
                potential_path = workspace_root / resource.path
                if potential_path.exists():
                    resolved_path = potential_path
                    source = "workspace"

            # 4. Fallback to system PATH for executables
            if not resolved_path and resource.is_executable:
                system_path = shutil.which(Path(resource.path).name)
                if system_path:
                    resolved_path = Path(system_path)
                    source = "system"

            if resolved_path and resolved_path.exists():
                print(
                    f"AppConfig INFO: Resolved '{name}' in '{source}': {resolved_path}",
                    file=sys.stderr,
                )
                if resource.is_executable and not os.access(resolved_path, os.X_OK):
                    raise ConfigurationError(
                        f"Resolved resource '{name}' at '{resolved_path}' is not executable."
                    )
                setattr(self, f"{name}_path", resolved_path)
            elif not resource.is_optional:
                raise BinaryNotFoundError(f"Could not resolve required resource '{name}'.")
            else:
                print(
                    f"AppConfig INFO: Optional resource '{name}' not found. Will be unavailable.",
                    file=sys.stderr,
                )
                setattr(self, f"{name}_path", None)

    def _set_derived_paths(self) -> None:
        """Sets configuration values that are derived from other settings."""
        self.tmux_socket_path = self.session_temp_dir / f"{self.kubezen_socket_name}.sock"
        self.current_kube_context_name = self.kubezen_initial_context

        # Handle kube config path
        if self.kube_config_path_override:
            kube_config_path = Path(self.kube_config_path_override)
            if not kube_config_path.exists():
                raise ConfigurationError(
                    f"Specified kube config path does not exist: {kube_config_path}"
                )
            if not kube_config_path.is_file():
                raise ConfigurationError(
                    f"Specified kube config path is not a file: {kube_config_path}"
                )
            self.kube_config_path = str(kube_config_path)
        else:
            # Use default kube config path
            default_kube_config = Path.home() / ".kube" / "config"
            if default_kube_config.exists():
                self.kube_config_path = str(default_kube_config)
            else:
                self.kube_config_path = ""

    def get_temp_dir_path(self) -> str:
        """Returns the session's temporary directory path as a string."""
        return str(self.session_temp_dir)

    def cleanup_temp_dirs(self) -> None:
        """Safely removes the temporary directories created by this config instance."""
        if self.debug_mode:
            return

        if self.session_temp_dir.exists():
            try:
                shutil.rmtree(self.session_temp_dir)
            except OSError as e:
                print(
                    f"WARNING: Failed to remove temp directory {self.session_temp_dir}: {e}",
                    file=sys.stderr,
                )

    def to_dict(self) -> Dict[str, Any]:
        """Converts the configuration to a dictionary for serialization."""
        result = {}
        # Only serialize instance attributes, not class attributes
        for field_name in self.__dataclass_fields__:
            if field_name.startswith("_") or field_name in ["CONFIG_VALUES", "REQUIRED_RESOURCES"]:
                continue
            value = getattr(self, field_name)
            if isinstance(value, Path):
                result[field_name] = str(value)
            else:
                result[field_name] = value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KubeZenConfig":
        """Creates a KubeZenConfig instance from a dictionary."""
        # First, create a copy of the data
        config_data = data.copy()

        # Remove any fields that are marked as init=False
        for field_name, field_info in cls.__dataclass_fields__.items():
            if not field_info.init:
                config_data.pop(field_name, None)

        # Convert string paths back to Path objects for the core fields
        for field_name in cls.__dataclass_fields__:
            if field_name in config_data and isinstance(config_data[field_name], str):
                if field_name.endswith("_path") or field_name in [
                    "session_temp_dir",
                    "temp_log_dir",
                    "temp_fzf_dir",
                ]:
                    config_data[field_name] = Path(config_data[field_name])

        # Create the instance with only the core fields
        instance = cls(**config_data)

        # Now set the derived fields
        for field_name, field_info in cls.__dataclass_fields__.items():
            if not field_info.init and field_name in data:
                value = data[field_name]
                if isinstance(value, str) and (
                    field_name.endswith("_path")
                    or field_name in ["session_temp_dir", "temp_log_dir", "temp_fzf_dir"]
                ):
                    value = Path(value)
                setattr(instance, field_name, value)

        return instance


class AppConfig:
    """
    A singleton wrapper around KubeZenConfig for backward compatibility.
    This class will be deprecated in favor of using KubeZenConfig directly.
    """

    _instance: Optional[AppConfig] = None
    _config: Optional[KubeZenConfig] = None

    def __new__(cls) -> AppConfig:
        if cls._instance is None:
            cls._instance = super(AppConfig, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._config is None:
            config_file_path = os.environ.get("KUBEZEN_CONFIG_FILE")
            if config_file_path and Path(config_file_path).exists():
                with open(config_file_path, "r") as f:
                    data = json.load(f)
                self._config = KubeZenConfig.from_dict(data)
            else:
                self._config = KubeZenConfig.from_env()

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the underlying KubeZenConfig instance."""
        value = getattr(self._config, name)
        # Only convert specific paths to strings that are used in commands
        if isinstance(value, Path) and name in [
            "fzf_item_reader_script_path",
            "fzf_tmux_script_path",
            "core_ui_runner_script_path",
            "kubezen_tmux_config_path",
            "mouse_swipe_plugin_script_path",
        ]:
            return str(value)
        return value

    def export_to_file(self) -> Path:
        """Exports the current configuration to a JSON file in the temp directory."""
        if self._config is None:
            raise ConfigurationError("Cannot export an uninitialized configuration.")
        config_path = self._config.session_temp_dir / CONFIG_EXPORT_FILENAME
        with open(config_path, "w") as f:
            json.dump(self._config.to_dict(), f, indent=4)
        return config_path


# --- Singleton Instance ---
try:
    app_config = AppConfig()
except ConfigurationError as e:
    print(f"[config.py CRITICAL] Failed to initialize KubeZen AppConfig: {e}", file=sys.stderr)
    # Exit gracefully if configuration fails
    sys.exit(1)
except Exception as e:
    print(
        f"[config.py CRITICAL] An unexpected error occurred during AppConfig initialization: {e}",
        file=sys.stderr,
    )
    # Exit for any other unexpected errors
    sys.exit(1)
