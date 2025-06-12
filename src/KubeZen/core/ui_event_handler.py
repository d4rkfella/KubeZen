from __future__ import annotations
from typing import TYPE_CHECKING, Any, Optional, Tuple
import asyncio

from KubeZen.core import signals
from KubeZen.core.events import (
    FzfSelectionEvent,
    EnterKeyEvent,
    FzfRefreshRequestEvent,
    ResourceStoreUpdateEvent,
)
from KubeZen.core.exceptions import ActionCancelledError, ActionFailedError
from KubeZen.core.signals import (
    ExitApplicationSignal,
    PushViewSignal,
    ToParentSignal,
    ToParentWithResultSignal,
    ReloadSignal,
    StaySignal,
)
from KubeZen.ui.views.view_base import BaseUIView
from KubeZen.core.service_base import ServiceBase

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices
    from KubeZen.core.event_bus import EventBus
    from KubeZen.ui.navigation_coordinator import NavigationCoordinator


class UiEventHandler(ServiceBase):
    def __init__(self, app_services: AppServices):
        super().__init__(app_services)
        assert (
            self.app_services.event_bus is not None
        ), "UiEventHandler requires EventBus from AppServices"
        self.event_bus: EventBus = self.app_services.event_bus
        assert (
            self.app_services.navigation_coordinator is not None
        ), "UiEventHandler requires NavigationCoordinator from AppServices"
        self.navigation_coordinator: NavigationCoordinator = (
            self.app_services.navigation_coordinator
        )
        self._event_queue: asyncio.Queue[Tuple[str, Any]] = asyncio.Queue()
        self._processing_task: Optional[asyncio.Task[None]] = None
        self._is_processing = False

    async def start(self) -> None:
        """Starts the event processing loop."""
        if self._processing_task is None:
            self._processing_task = asyncio.create_task(self._event_processor())
            self.logger.info("UiEventHandler event processing loop started.")

    async def stop(self) -> None:
        """Stops the event processing loop."""
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                self.logger.info("UiEventHandler event processing task cancelled.")
            finally:
                self._processing_task = None

    def subscribe_to_events(self) -> None:
        self.event_bus.subscribe(FzfSelectionEvent, self.handle_fzf_selection)
        self.event_bus.subscribe(EnterKeyEvent, self.handle_enter_key)
        self.event_bus.subscribe(FzfRefreshRequestEvent, self.handle_fzf_refresh_request)
        self.event_bus.subscribe(ResourceStoreUpdateEvent, self.handle_resource_store_update)

    async def handle_fzf_selection(self, event: FzfSelectionEvent) -> None:
        await self._event_queue.put(("fzf_selection", event.data))

    async def handle_resource_store_update(self, event: ResourceStoreUpdateEvent) -> None:
        self.logger.debug("[UI_HANDLER_DEBUG] Received event")
        await self._event_queue.put(("resource_update", event))

    async def handle_enter_key(self, event: EnterKeyEvent) -> None:
        await self._event_queue.put(("enter", event.data))

    async def handle_fzf_refresh_request(self, event: FzfRefreshRequestEvent) -> None:
        await self._event_queue.put(("reload_signal", event.data))

    async def _event_processor(self) -> None:
        """The core loop that processes events from the queue."""
        while True:
            event_key, event_data = None, None
            try:
                event_key, event_data = await self._event_queue.get()
                self.logger.debug(
                    f"[QUEUE_PULL] Pulled event '{event_key}' from queue. Data type: {type(event_data)}. Data: {event_data}"
                )
                if self._is_processing:
                    self.logger.warning(
                        f"Ignoring event '{event_key}' because another is already being processed."
                    )
                    self._event_queue.task_done()
                    continue

                self._is_processing = True
                await self._process_ui_event(event_key, event_data)
                self._event_queue.task_done()
            except asyncio.CancelledError:
                self.logger.info("Event processor loop is shutting down.")
                break
            except Exception as e:
                log_key = event_key or "unknown_event"
                self.logger.error(
                    f"Error in event processor for event '{log_key}': {e}", exc_info=True
                )
            finally:
                self._is_processing = False

    async def _process_ui_event(self, event_key: str, event_data: Any) -> None:
        self.logger.debug(f"UiEventHandler: Processing UI event: '{event_key}'")

        signal: Optional[signals.NavigationSignal] = None
        fzf_actions: Optional[list[str]] = None

        try:
            current_view = self.navigation_coordinator.get_current_view()

            if event_key == "resource_update":
                if current_view:
                    signal = await self._handle_resource_update(event_data, current_view)
                else:
                    self.logger.debug("No active view for resource update, ignoring.")
                    signal = StaySignal()

            elif event_key == "reload_signal":
                self.logger.info("Processing a reload signal.")
                signal = ReloadSignal()

            elif event_key == "esc":
                signal = ToParentSignal()

            elif not current_view:
                self.logger.error("No current view to process event '{}'.".format(event_key))
                signal = StaySignal()

            elif event_key == "fzf_selection":
                action_code, display_text, _ = self._parse_fzf_event_data(event_data)
                if action_code == BaseUIView.GO_BACK_ACTION_CODE:
                    signal = ToParentSignal()
                else:
                    signal = await current_view.process_selection(
                        action_code,
                        display_text,
                        {"fzf_event_raw_line_data": event_data.get("fzf_event_raw_line_data")},
                    )

            else:
                self.logger.warning(f"Unhandled event key '{event_key}'.")
                signal = StaySignal()

            # --- Signal Processing ---
            while signal:
                self.logger.debug(f"Processing signal: {signal.__class__.__name__}")

                if isinstance(signal, PushViewSignal):
                    fzf_actions = await self.navigation_coordinator.push_view(
                        view_key=signal.view_key,
                        view_class=signal.view_class,
                        context=signal.context,
                    )
                    signal = None  # Signal handled
                elif isinstance(signal, ToParentWithResultSignal):
                    # This signal yields a sub-signal. It also returns the fzf_actions
                    # needed to refresh the parent view's display.
                    sub_signal, fzf_actions_from_pop = (
                        await self.navigation_coordinator.pop_view_with_result(
                            result=signal.result, context=signal.context
                        )
                    )
                    signal = sub_signal  # Let the loop handle the new signal
                    if fzf_actions_from_pop:
                        fzf_actions = fzf_actions_from_pop  # Capture the actions
                elif isinstance(signal, signals.PopViewSignal):
                    fzf_actions, _ = await self.navigation_coordinator.pop_view(
                        context=signal.context
                    )
                    signal = None  # Signal handled
                elif isinstance(signal, ToParentSignal):
                    fzf_actions, _ = await self.navigation_coordinator.pop_view(
                        context=signal.context
                    )
                    signal = None  # Signal handled
                elif isinstance(signal, ReloadSignal):
                    fzf_actions = await self.navigation_coordinator.refresh_current_view(
                        context=signal.context
                    )
                    signal = None  # Signal handled
                elif isinstance(signal, StaySignal):
                    signal = None  # Signal handled
                elif isinstance(signal, ExitApplicationSignal):
                    self.app_services.shutdown_requested = True
                    signal = None  # Signal handled
                else:
                    self.logger.warning(
                        f"Unhandled signal type: {type(signal)}. Breaking from loop."
                    )
                    signal = None

            if fzf_actions:
                assert self.app_services.fzf_ui_manager is not None
                await self.app_services.fzf_ui_manager.send_actions(fzf_actions)

        except (ActionFailedError, ActionCancelledError) as e:
            self.logger.warning(f"Action did not complete: {e}")
        except Exception as e:
            self.logger.error(f"Error processing UI event '{event_key}': {e}", exc_info=True)

    def _parse_fzf_event_data(self, event_data: Any) -> Tuple[str, str, Optional[str]]:
        raw_line_data = (
            event_data.get("fzf_event_raw_line_data") if isinstance(event_data, dict) else None
        )
        action_code, display_text, session_id = "", "", None

        if raw_line_data and isinstance(raw_line_data, str):
            parts = raw_line_data.split("|")
            if len(parts) >= 3:
                action_code, session_id, display_text = parts[0], parts[1], parts[2]
            else:
                action_code = parts[0]
                display_text = parts[1] if len(parts) > 1 else action_code

        return (
            action_code.strip(),
            display_text.strip(),
            session_id.strip() if session_id else None,
        )

    async def _handle_resource_update(
        self, event: ResourceStoreUpdateEvent, current_view: BaseUIView
    ) -> Optional[signals.NavigationSignal]:
        view_context = current_view.context
        view_type = current_view.VIEW_TYPE

        self.logger.debug(
            f"[RelevancyCheck] Incoming event: kind='{event.resource_kind_plural}', ns='{event.namespace}'. Current view: '{view_type}'"
        )

        is_relevant = False
        if view_type == "ResourceListView":
            view_resource_kind = view_context.get("current_kubernetes_resource_type")
            view_namespace = view_context.get("selected_namespace")
            if event.resource_kind_plural == view_resource_kind and (
                view_namespace is None
                or event.namespace == "all-namespaces"
                or event.namespace == view_namespace
            ):
                is_relevant = True
        elif view_type == "NamespaceSelectionView" and event.resource_kind_plural == "namespaces":
            is_relevant = True

        if is_relevant:
            self.logger.info(
                f"Relevant resource update for view '{view_type}', triggering reload."
            )
            return ReloadSignal()
        else:
            self.logger.debug(f"Update not relevant for view '{view_type}'.")
            return StaySignal()
