from __future__ import annotations
import importlib
import pkgutil
from pathlib import Path
from typing import Type, List
import logging

from KubeZen.ui.view_registry import ViewRegistry
from KubeZen.ui.views.view_base import BaseUIView

logger = logging.getLogger(__name__)


def _validate_view_class(view_class: Type[BaseUIView]) -> None:
    """
    Validates that a view class follows the required pattern.
    Raises ValueError with descriptive message if validation fails.
    """
    # Check inheritance
    if not issubclass(view_class, BaseUIView):
        raise ValueError(f"View class {view_class.__name__} must inherit from BaseUIView")

    # Check VIEW_TYPE
    if not hasattr(view_class, "VIEW_TYPE"):
        raise ValueError(f"View class {view_class.__name__} must define VIEW_TYPE class variable")
    if not isinstance(view_class.VIEW_TYPE, str):
        raise ValueError(f"View class {view_class.__name__}.VIEW_TYPE must be a string")
    if not view_class.VIEW_TYPE:
        raise ValueError(f"View class {view_class.__name__}.VIEW_TYPE cannot be empty")

    # Check required methods
    required_methods = ["get_fzf_configuration", "process_selection"]
    for method in required_methods:
        if not hasattr(view_class, method):
            raise ValueError(f"View class {view_class.__name__} must implement {method} method")
        if not callable(getattr(view_class, method)):
            raise ValueError(f"View class {view_class.__name__}.{method} must be a method")


def _discover_view_classes() -> tuple[List[Type[BaseUIView]], List[str]]:
    """
    Discovers all view classes in the views package.
    Returns a tuple containing:
    - A list of valid view classes that inherit from BaseUIView.
    - A list of error messages for views that failed to load.
    """
    view_classes = []
    error_messages = []
    views_package = Path(__file__).parent / "views"

    # Iterate through all Python files in the views directory
    for module_info in pkgutil.iter_modules([str(views_package)]):
        if module_info.name == "view_base":  # Skip the base class
            continue

        try:
            # Import the module
            module = importlib.import_module(f"KubeZen.ui.views.{module_info.name}")

            # Find all classes in the module that inherit from BaseUIView
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseUIView) and attr != BaseUIView:
                    try:
                        _validate_view_class(attr)
                        view_classes.append(attr)
                    except ValueError as e:
                        error_msg = f"Invalid view class {attr.__name__}: {e}"
                        logger.error(error_msg)
                        error_messages.append(error_msg)

        except Exception as e:
            error_msg = f"Error importing view module {module_info.name}: {e}"
            logger.error(error_msg)
            error_messages.append(error_msg)

    return view_classes, error_messages


def create_and_populate_view_registry() -> tuple[ViewRegistry, List[str]]:
    """
    Creates a ViewRegistry instance and populates it with all known UI views.
    Views are automatically discovered and registered.
    Returns a tuple of the registry and a list of any errors encountered.
    """
    # Create the registry
    registry = ViewRegistry()

    # Discover and register all views
    view_classes, errors = _discover_view_classes()
    for view_class in view_classes:
        # Get the view type from the class
        view_type = getattr(view_class, "VIEW_TYPE", view_class.__name__)
        registry.register_view(view_type, view_class)

    # Validate that the default view exists
    try:
        registry.get_default_view()
    except RuntimeError as e:
        error_msg = (
            f"Failed to create view registry: {e}. "
            "This is a critical error as the default view is required."
        )
        errors.append(error_msg)
        raise RuntimeError(error_msg) from e

    return registry, errors
