import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, PropertyMock
from textual.widgets import DataTable
from textual.app import App
from KubeZen.screens.base_screen import BaseResourceScreen
from KubeZen.core.resource_events import ResourceEventSource
from contextlib import contextmanager
from freezegun import freeze_time
import logging
import sys

# Set up logging to stdout
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Get the root logger and set it up
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(handler)

# Get our specific logger
log = logging.getLogger(__name__)

class TestApp(App):
    """A minimal app for testing."""
    def compose(self):
        yield from ()

class TestBaseScreen:
    @pytest.fixture
    def mock_event_source(self):
        return MagicMock(spec=ResourceEventSource)

    @pytest.fixture
    def mock_table(self):
        table = MagicMock(spec=DataTable)
        # Set up the table mock with required attributes and methods
        table.is_mounted = True
        
        # Create a proper mock for columns that mimics DataTable's structure
        column_key = MagicMock()
        column_key.value = "Age"
        table.columns = {column_key: MagicMock()}
        
        # Track cell values for age updates
        cell_values = {}
        def get_cell(row_key, column=None):
            return cell_values.get(row_key, "0s")
        def update_cell(row_key, column, value):
            cell_values[row_key] = value
            
        table.get_cell = MagicMock(side_effect=get_cell)
        table.update_cell = MagicMock(side_effect=update_cell)
        return table

    @pytest.fixture
    async def test_app(self):
        app = TestApp()
        async with app.run_test(size=(80, 24)):  # Run the app in test mode
            yield app

    @pytest.fixture
    async def base_screen(self, mock_event_source, mock_table, test_app):
        class TestScreen(BaseResourceScreen):
            RESOURCE_TYPE = "test"
            COLUMNS = [{"label": "Age", "width": 10}]
            
            def _format_row(self, item):
                return ["test"]
            
            async def on_mount(self) -> None:
                """Override on_mount to avoid DataTable initialization issues in tests."""
                self._column_key_to_index = {"Age": 0}  # Simplified for testing
                self._items_to_update_secs = []
                self._items_to_update_min_sec = []
                self._items_to_update_mins = []
                self._items_to_update_hour_min = []
                self._items_to_update_hours = []
                self._items_to_update_day_hour = []
                self._items_to_update_days = []
                self._age_update_lock = AsyncMock()  # Mock the lock
                self._age_update_lock.locked = MagicMock(return_value=False)  # Mock locked() to always return False
                self._age_update_lock.__aenter__ = AsyncMock()  # Mock async context manager
                self._age_update_lock.__aexit__ = AsyncMock()
                self.app = test_app  # Set the app property
                self.app.batch_update = MagicMock()  # Mock batch_update context manager
                self.app.batch_update.__enter__ = MagicMock()
                self.app.batch_update.__exit__ = MagicMock()
        
        screen = TestScreen(mock_event_source)
        screen.query_one = MagicMock(return_value=mock_table)
        test_app.push_screen(screen)
        return screen

    @pytest.mark.asyncio
    async def test_age_tracking_transitions(self, base_screen, mock_table):
        # Create a pod at the start time
        with freeze_time("2024-01-01 12:00:00+00:00") as frozen_time:
            pod = {
                "metadata": {
                    "name": "test-pod",
                    "creationTimestamp": datetime.now(timezone.utc).isoformat()
                }
            }
            
            # Add pod to tracking
            base_screen._add_item_to_age_tracker(pod)
            
            # Should be in seconds bucket initially
            assert any(item[0] == "test-pod" for item in base_screen._items_to_update_secs)
            assert not any(item[0] == "test-pod" for item in base_screen._items_to_update_min_sec)
            
            print("\nInitial state:")
            print(f"Current time: {datetime.now(timezone.utc)}")
            print(f"Pod creation time: {datetime.fromisoformat(pod['metadata']['creationTimestamp'])}")
            print(f"Age in minutes: {(datetime.now(timezone.utc) - datetime.fromisoformat(pod['metadata']['creationTimestamp'])).total_seconds() / 60}")
            print(f"Seconds bucket: {base_screen._items_to_update_secs}")
            print(f"Minutes:seconds bucket: {base_screen._items_to_update_min_sec}")
            
            # Move time forward 2 minutes and 1 second to ensure we're past the threshold
            frozen_time.move_to("2024-01-01 12:02:01+00:00")
            
            print("\nBefore 2-minute update:")
            print(f"Current time: {datetime.now(timezone.utc)}")
            print(f"Pod creation time: {datetime.fromisoformat(pod['metadata']['creationTimestamp'])}")
            print(f"Age in minutes: {(datetime.now(timezone.utc) - datetime.fromisoformat(pod['metadata']['creationTimestamp'])).total_seconds() / 60}")
            print(f"Seconds bucket: {base_screen._items_to_update_secs}")
            print(f"Minutes:seconds bucket: {base_screen._items_to_update_min_sec}")
            
            # Process the update
            await base_screen._update_ages()
            
            print("\nAfter 2-minute update:")
            print(f"Current time: {datetime.now(timezone.utc)}")
            print(f"Pod creation time: {datetime.fromisoformat(pod['metadata']['creationTimestamp'])}")
            print(f"Age in minutes: {(datetime.now(timezone.utc) - datetime.fromisoformat(pod['metadata']['creationTimestamp'])).total_seconds() / 60}")
            print(f"Seconds bucket: {base_screen._items_to_update_secs}")
            print(f"Minutes:seconds bucket: {base_screen._items_to_update_min_sec}")
            
            # Should move to minutes:seconds bucket
            assert not any(item[0] == "test-pod" for item in base_screen._items_to_update_secs), \
                "Pod should not be in seconds bucket after 2 minutes"
            assert any(item[0] == "test-pod" for item in base_screen._items_to_update_min_sec), \
                "Pod should be in minutes:seconds bucket after 2 minutes"
            
            # Move time forward to 10 minutes and 1 second to ensure we're past the threshold
            frozen_time.move_to("2024-01-01 12:10:01+00:00")
            
            print("\nBefore 10-minute update:")
            print(f"Current time: {datetime.now(timezone.utc)}")
            print(f"Pod creation time: {datetime.fromisoformat(pod['metadata']['creationTimestamp'])}")
            print(f"Age in minutes: {(datetime.now(timezone.utc) - datetime.fromisoformat(pod['metadata']['creationTimestamp'])).total_seconds() / 60}")
            print(f"Minutes:seconds bucket: {base_screen._items_to_update_min_sec}")
            print(f"Minutes bucket: {base_screen._items_to_update_mins}")
            
            # Process the update
            await base_screen._update_ages()
            
            print("\nAfter 10-minute update:")
            print(f"Current time: {datetime.now(timezone.utc)}")
            print(f"Pod creation time: {datetime.fromisoformat(pod['metadata']['creationTimestamp'])}")
            print(f"Age in minutes: {(datetime.now(timezone.utc) - datetime.fromisoformat(pod['metadata']['creationTimestamp'])).total_seconds() / 60}")
            print(f"Minutes:seconds bucket: {base_screen._items_to_update_min_sec}")
            print(f"Minutes bucket: {base_screen._items_to_update_mins}")
            
            # Should move to minutes bucket
            assert not any(item[0] == "test-pod" for item in base_screen._items_to_update_min_sec), \
                "Pod should not be in minutes:seconds bucket after 10 minutes"
            assert any(item[0] == "test-pod" for item in base_screen._items_to_update_mins), \
                "Pod should be in minutes bucket after 10 minutes"
            
            # Verify the pod is being tracked in exactly one bucket
            all_buckets = [
                base_screen._items_to_update_secs,
                base_screen._items_to_update_min_sec,
                base_screen._items_to_update_mins,
                base_screen._items_to_update_hour_min,
                base_screen._items_to_update_hours,
                base_screen._items_to_update_day_hour,
                base_screen._items_to_update_days
            ]
            pod_count = sum(1 for bucket in all_buckets for item in bucket if item[0] == "test-pod")
            assert pod_count == 1, "Pod should be tracked in exactly one bucket"
            
            # Verify table updates were called
            mock_table.update_cell.assert_called() 