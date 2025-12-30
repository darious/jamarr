#!/bin/bash
set -e

# Run only slow-marked tests
./test.sh -m "slow"
