
import pytest

from app.scanner.core import get_shared_client, close_shared_client

@pytest.mark.asyncio
async def test_shared_client_reuse():
    print("Getting client 1...")
    client1 = get_shared_client()
    
    print("Getting client 2...")
    client2 = get_shared_client()
    
    assert client1 is client2, "Clients are not the same instance!"
    assert not client1.is_closed, "Client should be open"
    
    print("Closing client...")
    await close_shared_client()
    
    assert client1.is_closed, "Client 1 should be closed"
    
    print("Getting new client 3...")
    client3 = get_shared_client()
    
    assert client3 is not client1, "Client 3 should be a new instance"
    assert not client3.is_closed, "Client 3 should be open"
    
    await close_shared_client()
