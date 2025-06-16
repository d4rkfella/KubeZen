from typing import Optional
from .watched_resource_store import WatchedResourceStore
from .watched_resource_store_adapter import WatchedResourceStoreAdapter
from .resource_events import ResourceEventSource

def create_resource_event_source(store: Optional[WatchedResourceStore] = None) -> ResourceEventSource:
    """Creates a ResourceEventSource from a WatchedResourceStore.
    
    Args:
        store: Optional WatchedResourceStore instance. If not provided, a new one will be created.
        
    Returns:
        A ResourceEventSource that can be used by screens.
    """
    if store is None:
        from textual.app import get_app
        store = WatchedResourceStore(get_app())
    
    return WatchedResourceStoreAdapter(store) 