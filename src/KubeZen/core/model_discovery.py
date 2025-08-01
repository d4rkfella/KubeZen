from __future__ import annotations
import inspect
from typing import Type, AsyncGenerator, Generator, Union
import logging
import pkgutil
import importlib

from .. import models
from KubeZen.models.base import UIRow
from KubeZen.models.customresourcedefinitions import CustomResourceDefinitionRow
from KubeZen.models.crd_model_factory import create_model_from_crd
from .kubernetes_client import KubernetesClient
from kubernetes_asyncio.client.rest import ApiException
import asyncio

log = logging.getLogger(__name__)


def discover_standard_models() -> Generator[tuple[str, Type[UIRow]], None, None]:
    """
    Recursively discovers all concrete UIRow subclasses with a 'plural' attribute.
    Yields them as (key, model_class) tuples.
    """

    # Ensure all modules are loaded
    for _, module_name, _ in pkgutil.walk_packages(
        models.__path__, models.__name__ + "."
    ):
        importlib.import_module(module_name)

    def _traverse(
        cls: Union[type, Type[UIRow]],
    ) -> Generator[tuple[str, Type[UIRow]], None, None]:
        for subclass in cls.__subclasses__():
            if not inspect.isabstract(subclass):
                plural_name = getattr(subclass, "plural", None)
                if not plural_name:
                    log.warning(
                        f"Found UIRow subclass '{subclass.__name__}' without a 'plural' attribute."
                    )
                else:
                    api_info = getattr(subclass, "api_info", None)
                    group = api_info.group if api_info else ""
                    key = f"{group}/{plural_name}" if group else plural_name
                    yield key, subclass
            yield from _traverse(subclass)

    yield from _traverse(UIRow)


async def discover_crd_models(
    client: KubernetesClient,
) -> AsyncGenerator[tuple[str, Type[UIRow]], None]:
    """
    Discovers all CRDs and yields dynamic UIRow models for them concurrently as they complete.
    """
    try:
        api_client_name = CustomResourceDefinitionRow.api_info.client_name
        crd_client = getattr(client, api_client_name)
        crds = await asyncio.wait_for(
            crd_client.list_custom_resource_definition(),
            timeout=5
        )

        async def process_crd(crd):
            try:
                model = await asyncio.to_thread(create_model_from_crd, crd)
                if model:
                    key = f"{model.api_info.group}/{model.plural}"
                    return key, model
            except (TypeError, ValueError) as e:
                log.exception("Model creation error from CRD: %s", e)
            except Exception as e:
                log.exception("Unexpected error creating model: %s", e)
            return None

        tasks = [asyncio.create_task(process_crd(crd)) for crd in crds.items]

        for completed in asyncio.as_completed(tasks):
            result = await completed
            if result:
                yield result

    except AttributeError as e:
        log.error("Invalid API client attribute: %s", e)
        raise
    except asyncio.TimeoutError:
        log.warning("CRD list request timed out — possible network issue.")
        raise
    except ApiException as e:
        log.error("Kubernetes API error while listing CRDs: %s", e)
        raise
    except Exception as e:
        log.error("Unexpected error during CRD model discovery: %s", e)
        raise
