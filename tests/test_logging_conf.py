import logging
import os
import time
from app.logging_conf import configure_logging

def test_logging_configuration():
    # Setup
    log_dir = "cache/log"
    if os.path.exists(log_dir):
        import shutil
        shutil.rmtree(log_dir)
        
    configure_logging()
    
    # 1. Backend/Root Log
    root_logger = logging.getLogger()
    root_logger.info("TEST-BACKEND-MSG")
    
    # 2. Scanner Log
    scan_logger = logging.getLogger("scanner")
    scan_logger.debug("TEST-SCANNER-DEBUG")
    scan_logger.info("TEST-SCANNER-INFO")
    
    # 3. UPnP Log
    upnp_logger = logging.getLogger("app.upnp.manager")
    upnp_logger.debug("TEST-UPNP-DEBUG")
    
    upnp_lib_logger = logging.getLogger("async_upnp_client.some.module")
    upnp_lib_logger.warning("TEST-UPNP-LIB-WARN")
    
    # 4. Player Log
    player_logger = logging.getLogger("app.api.player")
    player_logger.info("TEST-PLAYER-INFO")
    
    # 5. Frontend Log
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.info("TEST-FRONTEND-ACCESS")
    access_logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "203.0.113.9:1234",
        "GET",
        "/api/stream/1?access_token=SECRET_TOKEN&foo=bar",
        "1.1",
        200,
    )
    
    # 6. Monitoring Logs
    app_access_logger = logging.getLogger("app.monitoring.access")
    app_access_logger.info("TEST-APP-ACCESS path=/api/albums")

    security_logger = logging.getLogger("app.security.audit")
    security_logger.warning(
        "TEST-SECURITY Authorization: Bearer SECRET_BEARER password=SECRET_PASSWORD "
        "lastfm_session_key=SECRET_LASTFM"
    )
    
    # Filter Test
    access_logger.info("GET /api/player/state HTTP/1.1") # Should be filtered out
    
    # Wait for flush
    time.sleep(1)
    
    # Validation
    assert os.path.exists(os.path.join(log_dir, "backend.log"))
    assert os.path.exists(os.path.join(log_dir, "scanner.log"))
    assert os.path.exists(os.path.join(log_dir, "upnp.log"))
    assert os.path.exists(os.path.join(log_dir, "player.log"))
    assert os.path.exists(os.path.join(log_dir, "frontend.log"))
    assert os.path.exists(os.path.join(log_dir, "access.log"))
    assert os.path.exists(os.path.join(log_dir, "security.log"))
    
    # Check Content
    with open(os.path.join(log_dir, "backend.log"), "r") as f:
        content = f.read()
        assert "TEST-BACKEND-MSG" in content
        # Ensure no duplication
        assert content.count("TEST-BACKEND-MSG") == 1, "Duplicate backend logs detected!"
        # Ensure split logs strictly DO NOT appear in backend log (except maybe warnings if they bubble up differently, but we filtered them)
        assert "TEST-SCANNER-DEBUG" not in content
        assert "TEST-UPNP-DEBUG" not in content
        assert "TEST-PLAYER-INFO" not in content
        assert "TEST-SECURITY" not in content
        
    with open(os.path.join(log_dir, "scanner.log"), "r") as f:
        content = f.read()
        assert "TEST-SCANNER-DEBUG" in content
        assert "TEST-SCANNER-INFO" in content
        
    with open(os.path.join(log_dir, "upnp.log"), "r") as f:
        content = f.read()
        assert "TEST-UPNP-DEBUG" in content
        assert "TEST-UPNP-LIB-WARN" in content
        
    with open(os.path.join(log_dir, "player.log"), "r") as f:
        content = f.read()
        assert "TEST-PLAYER-INFO" in content
        
    with open(os.path.join(log_dir, "frontend.log"), "r") as f:
        content = f.read()
        assert "TEST-FRONTEND-ACCESS" in content
        assert "GET /api/player/state" not in content
        assert "SECRET_TOKEN" not in content
        assert "foo=bar" not in content

    with open(os.path.join(log_dir, "access.log"), "r") as f:
        content = f.read()
        assert "TEST-APP-ACCESS" in content

    with open(os.path.join(log_dir, "security.log"), "r") as f:
        content = f.read()
        assert "TEST-SECURITY" in content
        assert "SECRET_BEARER" not in content
        assert "SECRET_PASSWORD" not in content
        assert "SECRET_LASTFM" not in content
        assert "[REDACTED]" in content
