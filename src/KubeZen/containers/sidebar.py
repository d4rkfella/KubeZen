from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from textual.widgets import Tree


from ..models.base import CATEGORIES, Category

if TYPE_CHECKING:
    from ..models.base import UIRow
    from ..app import KubeZenTuiApp


log = logging.getLogger(__name__)


class Sidebar(Tree):
    """Sidebar container for the resource tree."""

    app: "KubeZenTuiApp"  # type: ignore[assignment]

    can_focus: bool = False
    show_guides: bool = False
    guide_depth: int = 3
    auto_expand: bool = True

    async def on_mount(self) -> None:
        """Initialize widget references."""
        await self._add_context_node()

    async def _add_context_node(self) -> None:
        try:
            current_context = await self.app.kubernetes_client.get_current_context()
            if not current_context:
                self.root.add_leaf("Error: No current context found.")
                return
            log.debug(f"Current context: {current_context}")
        except Exception as e:
            log.error(f"Failed to get Kubernetes contexts: {e}", exc_info=True)
            self.root.add_leaf("Error: Could not load contexts.")
            return

        context_node = self.root.add(
            f"⎈ {current_context}",
            data={
                "type": "context",
                "name": current_context,
                "context": current_context,
            },
        )

    async def update_tree(self) -> None:
        """Updates the resource tree with contexts and resources."""
        with self.app.batch_update():
            context_node = self.root.children[0]
            # Group models by category
            grouped_models: dict[str, list[type[UIRow]]] = {}
            for model_cls in self.app.resource_models.values():
                category = model_cls.category
                if category not in grouped_models:
                    grouped_models[category] = []
                grouped_models[category].append(model_cls)

            # Sort categories based on their index
            sorted_categories = sorted(
                grouped_models.items(),
                key=lambda item: CATEGORIES.get(item[0], Category("", "", 999)).index,
            )

            for category, models_in_category in sorted_categories:
                category_info = CATEGORIES.get(category)

                # Get the label with icon
                if category_info:
                    category_label = f"{category_info.icon} {category_info.name}"
                else:
                    category_label = category

                # If a category has only one type of resource, add it as a leaf.
                if len(models_in_category) == 1 and category != "Custom Resources":
                    model_cls = models_in_category[0]
                    resource_key = model_cls.plural.lower()

                    # Add padding to the label to align with expandable nodes
                    padded_label = f"  {category_label}"

                    context_node.add_leaf(
                        padded_label,
                        data={
                            "type": "resource",
                            "resource_key": resource_key,
                            "model_class": model_cls,
                        },
                    )
                elif category == "Custom Resources":
                    # Handle CRDs separately to group them by api_group
                    crd_category_node = context_node.add(
                        category_label,
                        data={"type": "group", "name": "custom_resources"},
                    )

                    crd_model = next(
                        (
                            m
                            for m in models_in_category
                            if m.kind == "CustomResourceDefinition"
                        ),
                        None,
                    )
                    other_crd_models = [
                        m
                        for m in models_in_category
                        if m.kind != "CustomResourceDefinition"
                    ]

                    # Add the special 'Definitions' (CRD) model as the first leaf
                    if crd_model:
                        crd_category_node.add_leaf(
                            crd_model.display_name,
                            data={
                                "type": "resource",
                                "resource_key": crd_model.plural.lower(),
                                "model_class": crd_model,
                            },
                        )

                    # Group the rest of the CRDs by their api_group
                    grouped_crds: dict[str, list[type[UIRow]]] = {}
                    for model_cls in other_crd_models:
                        # For CRDs, we still need api_group
                        if hasattr(model_cls, "api_info"):
                            api_group = model_cls.api_info.group
                        else:
                            api_group = model_cls.api_info.group
                        if api_group not in grouped_crds:
                            grouped_crds[api_group] = []
                        grouped_crds[api_group].append(model_cls)

                    # Sort API groups based on the lowest index of a model within them
                    def get_min_index(models_in_group: list[type[UIRow]]) -> int:
                        return (
                            min(m.index for m in models_in_group)
                            if models_in_group
                            else 999
                        )

                    sorted_api_groups = sorted(
                        grouped_crds.items(),
                        key=lambda item: (get_min_index(item[1]), item[0]),
                    )

                    for api_group, crds_in_group in sorted_api_groups:
                        # Always create a node for the api_group for consistency.
                        api_group_node = crd_category_node.add(
                            api_group,
                            data={"type": "group", "name": api_group},
                        )
                        # Sort models within the group alphabetically by display_name
                        sorted_crds = sorted(
                            crds_in_group, key=lambda m: m.display_name
                        )
                        for model_cls in sorted_crds:
                            api_group_node.add_leaf(
                                model_cls.display_name,
                                data={
                                    "type": "resource",
                                    "resource_key": model_cls.plural.lower(),
                                    "model_class": model_cls,
                                },
                            )
                else:
                    # Otherwise, add it as a branch with resource leaves.
                    category_node = context_node.add(
                        category_label, data={"type": "group", "name": category.lower()}
                    )

                    # Sort models within the category based on their ui_index
                    sorted_models = sorted(models_in_category, key=lambda m: m.index)

                    for model_cls in sorted_models:
                        resource_key = model_cls.plural.lower()
                        category_node.add_leaf(
                            model_cls.display_name,
                            data={
                                "type": "resource",
                                "resource_key": resource_key,
                                "model_class": model_cls,
                            },
                        )

        if self.root.children:
            self.root.expand()
            self.root.children[0].expand()
