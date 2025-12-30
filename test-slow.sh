#!/bin/bash
set -euo pipefail

# Run only slow-marked tests (delegates to test.sh for setup/teardown)
./test.sh -m "slow"
