from __future__ import annotations
import os
import sys
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import ClassVar, Dict
import tempfile
import logging

log = logging.getLogger(__name__)


@dataclass
class Resource:
    """Represents a required resource in the system."""

    path: str
    is_executable: bool = False
    is_directory: bool = False
    is_optional: bool = False


class AppPaths:
    """Manages all application-related paths and resources."""

    REQUIRED_RESOURCES: ClassVar[Dict[str, Resource]] = {
        "tmux_config": Resource("assets/tmux/kubezen.tmux.conf"),
        "kubectl": Resource("kubectl", is_executable=True),
        "fzf": Resource("fzf", is_executable=True),
        "tmux": Resource("tmux", is_executable=True),
        "script": Resource("script", is_executable=True),
        "less": Resource("less", is_executable=True, is_optional=True),
        "vim": Resource("vim", is_executable=True, is_optional=True),
        "fzf_tmux_script": Resource("bin/fzf-tmux", is_executable=True),
        "fzf_log_search_script": Resource("bin/fzf_log_search.sh", is_executable=True),
        "pvc_file_browser_script": Resource(
            "bin/pvc_file_browser.sh", is_executable=True
        ),
    }

    def __init__(self) -> None:
        self.base_path: Path = self._determine_base_path()
        self.bin_path: Path = self.base_path / "bin"

        # Prepend the workspace bin directory to the PATH
        if self.bin_path.is_dir():
            os.environ["PATH"] = f"{self.bin_path}{os.pathsep}{os.environ['PATH']}"
            log.info("Prepended workspace bin to PATH: %s", self.bin_path)

        # Use existing temp directory from environment or create a new one
        temp_dir = os.environ.get("KUBEZEN_TEMP_DIR")
        if temp_dir:
            self.temp_dir = Path(temp_dir)
            log.info(
                "Using existing temp directory from environment: %s", self.temp_dir
            )
        else:
            self.temp_dir = Path(tempfile.mkdtemp(prefix="kubezen-"))
            os.environ["KUBEZEN_TEMP_DIR"] = str(self.temp_dir)
            log.info("Created new temp directory: %s", self.temp_dir)

        self.tmux_socket_path: Path = self.temp_dir / "tmux.sock"
        self.yappi_stats_path: Path = self.temp_dir / "kubezen.prof"

        # Resolve paths to external dependencies
        self.resources: Dict[str, Path | None] = self._resolve_paths()
        self.tmux_config_path: Path | None = self.resources.get("tmux_config")

    @staticmethod
    def _determine_base_path() -> Path:
        """Determines the base path for resources, handling PyInstaller environment."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            # pylint: disable=protected-access
            return Path(sys._MEIPASS)
        return Path(__file__).resolve().parent.parent.parent

    def _resolve_paths(self) -> Dict[str, Path | None]:
        """Resolves paths for all required resources, handling validation."""
        resolved_resources: Dict[str, Path | None] = {}
        for name, resource in self.REQUIRED_RESOURCES.items():
            resolved_path: Path | None = None

            # 1. Check relative to base path (for non-bin assets like configs)
            potential_path = self.base_path / resource.path
            if potential_path.exists():
                resolved_path = potential_path

            # 2. For executables, find them on the modified PATH
            if not resolved_path and resource.is_executable:
                system_path = shutil.which(resource.path)
                if system_path:
                    resolved_path = Path(system_path)

            if resolved_path:
                if resource.is_directory and not resolved_path.is_dir():
                    raise FileNotFoundError(
                        f"Required directory '{name}' not found at '{resolved_path}'"
                    )
                if resource.is_executable and not os.access(resolved_path, os.X_OK):
                    raise PermissionError(
                        f"Required executable '{name}' at '{resolved_path}' is not executable."
                    )

                log.info("Resolved resource '%s': %s", name, resolved_path)
                resolved_resources[name] = resolved_path
            elif not resource.is_optional:
                raise FileNotFoundError(
                    f"Could not resolve required resource '{name}' "
                    f"(expected at '{self.base_path / resource.path}')"
                )
            else:
                log.warning(
                    "Optional resource '%s' not found, feature will be unavailable.",
                    name,
                )
                resolved_resources[name] = None
        return resolved_resources

    def cleanup(self) -> None:
        """Removes the temporary directory."""
        if hasattr(self, "temp_dir") and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            logging.info("Cleaned up temporary directory: %s", self.temp_dir)

    def __del__(self) -> None:
        self.cleanup()


@dataclass
class AppConfig:
    """Manages application-wide configuration settings."""

    # --- Core Settings ---
    session_name: str = "KubeZen"

    # --- Watch Manager Settings ---
    watch_allow_bookmarks: bool = (
        True  # Enable bookmark events for better resource version tracking
    )
    watch_chunk_size: int = 500  # Get resources in chunks to avoid memory spikes
    watch_retry_delay: int = 5  # Delay in seconds before retrying after errors

    # --- Paths and Resources handled by AppPaths ---
    paths: AppPaths = field(init=False)

    # --- Singleton Pattern ---
    _instance: ClassVar[AppConfig | None] = None

    def __post_init__(self) -> None:
        """Initialize paths after dataclass init."""
        # Don't create AppPaths here - it's created in get_instance
        pass

    @classmethod
    def get_instance(cls) -> AppConfig:
        """Returns the singleton instance of the AppConfig."""
        if cls._instance is None:
            cls._instance = AppConfig()
            # Create AppPaths only once when singleton is created
            cls._instance.paths = AppPaths()
            log.info("AppConfig singleton initialized.")
        return cls._instance

    def cleanup(self) -> None:
        """Performs cleanup for AppConfig and its components."""
        self.paths.cleanup()

    def __del__(self) -> None:
        self.cleanup()
