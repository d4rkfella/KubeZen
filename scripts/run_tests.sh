#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Running static tests and checks...${NC}\n"

# Function to run a check and report its status
run_check() {
    echo -e "${YELLOW}Running $1...${NC}"
    $2
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ $1 passed${NC}\n"
    else
        echo -e "${RED}✗ $1 failed${NC}\n"
        exit 1
    fi
}

# 1. Run flake8
run_check "flake8" "flake8 ./src/KubeZen"

# 2. Run mypy for type checking
run_check "mypy" "mypy ./src/KubeZen"

# 3. Run pylint
run_check "pylint" "pylint ./src/KubeZen"

# 4. Run black in check mode
run_check "black" "black --check ./src/KubeZen"

# 5. Run isort in check mode
run_check "isort" "isort --check-only ./src/KubeZen"

echo -e "${GREEN}All checks passed!${NC}" 