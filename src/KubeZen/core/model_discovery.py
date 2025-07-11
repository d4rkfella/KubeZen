from __future__ import annotations
import inspect
from typing import Dict, Type
import logging
import pkgutil
import importlib

from .. import models
from KubeZen.models.base import UIRow
from KubeZen.models.customresourcedefinitions import CustomResourceDefinitionRow
from KubeZen.models.crd_model_factory import create_model_from_crd
from .kubernetes_client import KubernetesClient
from kubernetes_asyncio.client.rest import ApiException

log = logging.getLogger(__name__)


def _get_all_subclasses(cls: Type[UIRow]) -> set[Type[UIRow]]:
    """Recursively finds all subclasses of a given class."""
    return set(cls.__subclasses__()).union(
        [s for c in cls.__subclasses__() for s in _get_all_subclasses(c)]
    )

def discover_resource_models() -> Dict[str, Type[UIRow]]:
    """
    Discovers all UIRow subclasses from all modules within the 'models' package
    and builds a mapping from the resource 'plural' name to the model class.
    """
    discovered_models = {}
    log.debug("Starting model discovery in 'models' package...")

    # Dynamically import all modules in the model package so they are in memory
    for _, module_name, _ in pkgutil.walk_packages(
        models.__path__, models.__name__ + "."
    ):
        importlib.import_module(module_name)

    # Now that all modules are loaded, find all descendants of UIRow
    all_subclasses = _get_all_subclasses(UIRow)

    for subclass in all_subclasses:
        # Ignore abstract base classes
        if inspect.isabstract(subclass):
            continue

        plural_name = getattr(subclass, "plural", None)
        if plural_name:
            log.info(
                f"Discovered model: {subclass.__name__} with plural_name: {plural_name}"
            )
            discovered_models[plural_name] = subclass
        else:
            log.warning(
                f"Found UIRow subclass '{subclass.__name__}' without a 'plural' attribute."
            )

    log.info(
        f"Discovery complete. Found {len(discovered_models)} models: {list(discovered_models.keys())}"
    )
    return discovered_models


async def discover_crd_models(
    client: KubernetesClient,
) -> Dict[str, Type[UIRow]]:
    """
    Discovers all CRDs and creates dynamic UIRow models for them.
    """
    crd_models: Dict[str, Type[UIRow]] = {}
    try:
        api_client_name = CustomResourceDefinitionRow.api_info.client_name
        crd_client = getattr(client, api_client_name)
        crds = await crd_client.list_custom_resource_definition()

        for crd in crds.items:
            model = create_model_from_crd(crd)
            if model:
                log.debug(f"Created model for CRD: {model.plural}")
                crd_models[model.plural] = model

    except AttributeError as e:
        log.exception("Invalid API client attribute: %s", e)
    except ApiException as e:
        log.exception("Kubernetes API error while listing CRDs: %s", e)
    except (TypeError, ValueError) as e:
        log.exception("Model creation error from CRD: %s", e)
    except Exception as e:
        log.exception("Unexpected error during CRD model discovery: %s", e)

    return crd_models


_cached_all_models: list[Type[UIRow]] | None = None


def get_all_model_classes() -> list[Type[UIRow]]:
    """Returns a list of all UIRow subclasses."""
    global _cached_all_models
    if _cached_all_models is None:
        _cached_all_models = list(discover_resource_models().values())
    return _cached_all_models


_cached_models: Dict[str, Type[UIRow]] | None = None


def get_model_for_resource(resource_key: str) -> Type[UIRow] | None:
    """
    Retrieves the UIRow model class for a given resource key (plural form).
    Caches the discovered models on first run.
    """
    global _cached_models
    if _cached_models is None:
        _cached_models = discover_resource_models()

    return _cached_models.get(resource_key)
