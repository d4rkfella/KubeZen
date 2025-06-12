"""KubeZen Core Custom Exceptions"""


class KubeZenError(Exception):
    """Base class for all KubeZen application-specific exceptions."""


class ConfigurationError(KubeZenError):
    """Custom exception for configuration errors."""


class BinaryNotFoundError(ConfigurationError):
    """Custom exception for when a required binary/resource is not found."""


class TmuxError(KubeZenError):
    """Base class for Tmux related errors within KubeZen."""

    pass


class TmuxCommandError(TmuxError):
    """Generic error for a command failing in tmux."""

    pass


class TmuxCommandFailedError(TmuxCommandError):
    """Indicates a command executed in tmux failed (e.g., non-zero exit, or specific failure sentinel returned internally)."""

    pass


class TmuxCommandInterruptedError(TmuxCommandError):
    """Indicates a command executed in tmux was interrupted (e.g., by KeyboardInterrupt during wait)."""

    pass


class TmuxEnvironmentError(KubeZenError):
    """Raised for issues with the tmux environment (e.g., server not found)."""

    pass


class FzfError(KubeZenError):
    """Base class for FZF related errors within KubeZen."""

    pass


class FzfLaunchError(FzfError):
    """Error during FZF process launch."""

    pass


class UserInputError(KubeZenError):
    """Base class for errors encountered during user input operations via the input_helper script."""

    pass


class UserInputCancelledError(UserInputError):
    """Indicates the user cancelled the input operation."""

    pass


class UserInputFailedError(KubeZenError):
    """Raised when user input via tmux fails or times out."""

    pass


class TmuxOperationError(KubeZenError):
    """Indicates an error during a tmux operation that isn't covered by more specific exceptions."""

    pass


class ActionFailedError(KubeZenError):
    """Raised when a refactored Action class fails to execute."""

    pass


class ActionCancelledError(KubeZenError):
    """Raised when an action is explicitly cancelled by the user (e.g., at a confirmation prompt)."""

    pass


class K8sClientError(Exception):
    """Raised when a Kubernetes client API call fails."""

    pass
