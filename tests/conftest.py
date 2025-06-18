import pytest
import asyncio
from datetime import datetime, timezone

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_now(monkeypatch):
    """Mock datetime.now to return a fixed time."""
    class MockDatetime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 6, 16, 14, 0, 0, tzinfo=timezone.utc)
    
    monkeypatch.setattr("KubeZen.screens.base_screen.datetime", MockDatetime)
    return MockDatetime.now() 