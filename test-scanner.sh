#!/bin/bash
# Test script for the new v3 scanner pipeline
#
# Usage:
#   ./test-scanner.sh           # Run all v3 tests
#   ./test-scanner.sh -v        # Verbose output
#   ./test-scanner.sh -k models # Run only tests matching "models"

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Scanner V3 Pipeline Test Suite${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# Set PYTHONPATH
export PYTHONPATH=/root/code/jamarr

# Default pytest args
PYTEST_ARGS="tests/scanner/test_v3_*.py"

# Add any additional args passed to script
if [ $# -gt 0 ]; then
    PYTEST_ARGS="$PYTEST_ARGS $@"
fi

# Run tests
echo -e "${YELLOW}Running tests...${NC}"
echo ""

uv run pytest $PYTEST_ARGS --tb=short

# Show summary
echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Test Summary${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Test files:"
echo "  • test_v3_pipeline_models.py (16 tests)"
echo "  • test_v3_pipeline_base.py (5 tests)"
echo "  • test_v3_pipeline_stages.py (26 tests)"
echo "  • test_v3_pipeline_planner.py (11 tests)"
echo "  • test_v3_pipeline_executor.py (8 tests)"
echo "  • test_v3_pipeline_integration.py (5 tests)"
echo ""
echo -e "${GREEN}Total: 71 tests${NC}"
echo ""
