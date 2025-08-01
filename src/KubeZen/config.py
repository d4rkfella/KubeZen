from __future__ import annotations
import os
import sys
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import ClassVar, Dict, TypedDict, Required
import tempfile
import logging


log = logging.getLogger(__name__)


class Resource(TypedDict):
    path: Required[str]
    is_executable: Required[bool]
    is_directory: Required[bool]


class AppPaths:
    """Manages all application-related paths and resources."""

    REQUIRED_RESOURCES: ClassVar[Dict[str, Resource]] = {
        "tmux-config": Resource(
            path="assets/tmux/kubezen.tmux.conf",
            is_executable=False,
            is_directory=False,
        ),
        "kubectl": Resource(
            path="bin/kubectl",
            is_executable=True,
            is_directory=False,
        ),
        "vim": Resource(
            path="bin/vim",
            is_executable=True,
            is_directory=False,
        ),
        "fzf": Resource(
            path="bin/fzf",
            is_executable=True,
            is_directory=False,
        ),
        "fzf_log_search": Resource(
            path="bin/fzf_log_search.sh",
            is_executable=True,
            is_directory=False,
        ),
        "vimrc": Resource(
            path="assets/runtime_config/app.vimrc",
            is_executable=False,
            is_directory=False,
        ),
    }

    def __init__(self) -> None:
        self.base_path: Path = self._determine_base_path()
        self.bin_path: Path = self.base_path / "bin"
        self.resources: Dict[str, Path | None] = self._resolve_paths(
            AppPaths.REQUIRED_RESOURCES
        )

        # Prepend the workspace bin directory to the PATH
        if self.bin_path.is_dir():
            os.environ["PATH"] = f"{self.bin_path}{os.pathsep}{os.environ['PATH']}"
            log.info("Prepended workspace bin to PATH: %s", self.bin_path)

        # Use existing temp directory from environment or create a new one
        temp_dir = os.environ.get("TMPDIR")
        if temp_dir:
            self.temp_dir = Path(temp_dir)
            log.info(
                "Using existing temp directory from environment: %s", self.temp_dir
            )
        else:
            self.temp_dir = Path(tempfile.mkdtemp(prefix="kubezen-"))
            os.environ["TMPDIR"] = str(self.temp_dir)
            log.info("Created new temp directory: %s", self.temp_dir)

        os.environ["KUBE_EDITOR"] = f"vim -u {self.resources.get("vimrc")}"

        self.tmux_socket_path: Path = self.temp_dir / "tmux.sock"
        self.tmux_config_path: Path | None = self.resources.get("tmux_config")

    @staticmethod
    def _determine_base_path() -> Path:
        """Determines the base path for resources, handling PyInstaller environment."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        return Path(__file__).resolve().parent.parent.parent

    def _resolve_paths(
        self, required_resources: Dict[str, Resource]
    ) -> Dict[str, Path | None]:
        resolved_resources: Dict[str, Path | None] = {}

        for name, resource in required_resources.items():
            resolved_path: Path | None = None
            potential_path = self.base_path / resource["path"]

            if potential_path.exists():
                resolved_path = potential_path

            # If not found, and it's an executable, try PATH using the resource name
            if not resolved_path and resource["is_executable"]:
                system_path = shutil.which(name)
                if system_path:
                    resolved_path = Path(system_path)
                else:
                    raise FileNotFoundError(
                        f"Required executable '{name}' not found at '{potential_path}' or on PATH"
                    )

            # Final check that something was resolved
            if not resolved_path:
                raise FileNotFoundError(
                    f"Required resource '{name}' not found at '{potential_path}'"
                )

            # Validate based on type
            if resource["is_directory"]:
                if not resolved_path.is_dir():
                    raise FileNotFoundError(
                        f"Expected directory at '{resolved_path}' for resource '{name}', but it's missing or not a directory"
                    )
            elif resource["is_executable"]:
                if not os.access(resolved_path, os.X_OK):
                    raise PermissionError(
                        f"Expected executable at '{resolved_path}' for resource '{name}', but it is not executable"
                    )
            else:
                # Regular file: must exist and NOT be a directory
                if not resolved_path.is_file():
                    raise FileNotFoundError(
                        f"Expected file at '{resolved_path}' for resource '{name}', but it's missing or a directory"
                    )

            log.info("Resolved resource '%s': %s", name, resolved_path)
            resolved_resources[name] = resolved_path

        return resolved_resources

    def cleanup(self) -> None:
        """Removes the temporary directory."""
        if hasattr(self, "temp_dir") and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            logging.info("Cleaned up temporary directory: %s", self.temp_dir)


@dataclass(frozen=True)
class AppConfig:
    """Manages application-wide configuration settings."""

    _instance: ClassVar[AppConfig | None] = None

    session_name: str = "KubeZen"

    paths: AppPaths = field(default_factory=AppPaths)

    @classmethod
    def get_instance(cls) -> AppConfig:
        """Returns the singleton instance of the AppConfig."""
        if cls._instance is None:
            cls._instance = AppConfig()
            log.info("AppConfig singleton initialized.")
        return cls._instance

    def cleanup(self) -> None:
        """Performs cleanup for AppConfig and its components."""
        self.paths.cleanup()
