import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.upnp.device import UPnPDeviceControl

# Mock the Enum for TransportState since we can't import the real one easily if library is missing in some envs
class MockTransportState:
    PLAYING = MagicMock()
    PLAYING.name = "PLAYING"
    PLAYING.value = "PLAYING"
    STOPPED = MagicMock()
    STOPPED.name = "STOPPED"
    STOPPED.value = "STOPPED"

@pytest.mark.asyncio
async def test_get_transport_info_regression():
    """
    Verify that get_transport_info uses the correct API (properties) 
    instead of non-existent methods.
    """
    # 1. Setup Mock Manager and Device
    mock_manager = MagicMock()
    mock_dmr = MagicMock()
    
    # Crucial: The real DmrDevice does NOT have async_get_transport_info
    # We deliberately ensure this mock spec doesn't have it either
    del mock_dmr.async_get_transport_info 
    
    # It DOES have async_update and transport_state
    mock_dmr.async_update = AsyncMock()
    mock_dmr.transport_state = MockTransportState.PLAYING
    
    # Setup Manager to return our mock device
    mock_manager.active_renderer = "test-udn"
    mock_manager.dmr_devices = {"test-udn": mock_dmr}
    
    # 2. Instantiate Control Service
    control = UPnPDeviceControl(mock_manager)
    
    # 3. Call get_transport_info
    # If the code tries to call async_get_transport_info(), this will raise AttributeError
    state = await control.get_transport_info("test-udn")
    
    # 4. Verify
    assert state == "PLAYING"
    mock_dmr.async_update.assert_called_once()


@pytest.mark.asyncio
async def test_get_position_regression():
    """
    Verify that get_position uses UPnP action calls directly 
    instead of non-existent helper methods.
    """
    # 1. Setup Mock Manager and Device
    mock_manager = MagicMock()
    mock_dmr = MagicMock()
    
    # Crucial: The real DmrDevice does NOT have async_get_position_info
    del mock_dmr.async_get_position_info
    
    # It uses _action() to get the raw UPnP action
    mock_action = MagicMock()
    mock_action.async_call = AsyncMock(return_value={
        "RelTime": "0:01:30",
        "TrackDuration": "0:03:00"
    })
    mock_dmr._action.return_value = mock_action
    
    # Setup Manager
    mock_manager.active_renderer = "test-udn"
    mock_manager.dmr_devices = {"test-udn": mock_dmr}
    
    # 2. Instantiate Control Service
    control = UPnPDeviceControl(mock_manager)
    
    # 3. Call get_position
    # If the code tries to call async_get_position_info(), this will raise AttributeError
    pos, dur = await control.get_position("test-udn")
    
    # 4. Verify
    assert pos == 90 # 1m 30s
    assert dur == 180 # 3m
    mock_dmr._action.assert_called_with("AVT", "GetPositionInfo")
    mock_action.async_call.assert_called_once()
