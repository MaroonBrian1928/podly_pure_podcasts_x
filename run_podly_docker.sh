#!/bin/bash

YELLOW='\033[1;33m'
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

SERVER_URL=""

if [ -f "config/config.yml" ]; then
    SERVER_URL=$(grep "^server:" config/config.yml | cut -d' ' -f2- | tr -d ' ')

    if [ -n "$SERVER_URL" ]; then
        CLEAN_URL=$(echo "$SERVER_URL" | sed 's|^https\?://||')
        export VITE_API_URL="http://${CLEAN_URL}:5001"
        echo -e "${GREEN}Using server URL from config.yml: ${VITE_API_URL}${NC}"
    fi
fi

echo -e "${YELLOW}Checking dependencies...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker not found. Please install Docker first.${NC}"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo -e "${RED}Docker Compose not found. Please install Docker Compose V2.${NC}"
    exit 1
fi

BUILD_ONLY=false
TEST_BUILD=false
DETACHED=false
PRODUCTION_MODE=true
REBUILD=false
BRANCH_SUFFIX="main"
COMPOSE_FILES="-f compose.yml"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build)
            BUILD_ONLY=true
            ;;
        --test-build)
            TEST_BUILD=true
            ;;
        -d|--detach|-b|--background)
            DETACHED=true
            ;;
        --dev)
            REBUILD=true
            PRODUCTION_MODE=false
            ;;
        --rebuild)
            REBUILD=true
            PRODUCTION_MODE=false
            ;;
        --production)
            PRODUCTION_MODE=true
            ;;
        --branch=*)
            BRANCH_NAME="${1#*=}"
            BRANCH_SUFFIX="${BRANCH_NAME}"
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --build             Build containers only (don't start)"
            echo "  --test-build        Test build with no cache"
            echo "  -d, --detach        Run in detached/background mode"
            echo "  -b, --background    Alias for --detach"
            echo "  --dev               Development mode (build local image)"
            echo "  --rebuild           Rebuild containers before starting"
            echo "  --production        Use published image (default)"
            echo "  --branch=BRANCH     Use specific branch image tag prefix"
            echo "  -h, --help          Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--build] [--test-build] [-d|--detach] [-b|--background] [--dev] [--rebuild] [--production] [--branch=BRANCH_NAME] [-h|--help]"
            exit 1
            ;;
    esac
    shift
done

export PUID=$(id -u)
export PGID=$(id -g)

REQUIRE_AUTH_LOWER=$(printf '%s' "${REQUIRE_AUTH:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$REQUIRE_AUTH_LOWER" = "true" ] && [ -z "${PODLY_SECRET_KEY}" ]; then
    echo -e "${YELLOW}Warning: REQUIRE_AUTH is true but PODLY_SECRET_KEY is not set. Sessions will be reset on every restart.${NC}"
fi

if [ "$PRODUCTION_MODE" = true ]; then
    BRANCH="${BRANCH_SUFFIX}-latest"
    export BRANCH

    echo -e "${YELLOW}Production mode - using published image${NC}"
    echo -e "${YELLOW}  Branch tag: ${BRANCH}${NC}"
    if [ "$BRANCH_SUFFIX" != "main" ]; then
        echo -e "${GREEN}Using custom branch: ${BRANCH_SUFFIX}${NC}"
    fi
else
    export DEVELOPER_MODE=true
    echo -e "${YELLOW}Development mode - using local build from compose.yml${NC}"
fi

if [ "$BUILD_ONLY" = true ]; then
    echo -e "${YELLOW}Building containers only...${NC}"
    if ! docker compose $COMPOSE_FILES build; then
        echo -e "${RED}Build failed! Please fix the errors above and try again.${NC}"
        exit 1
    fi
    echo -e "${GREEN}Build completed successfully.${NC}"
elif [ "$TEST_BUILD" = true ]; then
    echo -e "${YELLOW}Testing build with no cache...${NC}"
    if ! docker compose $COMPOSE_FILES build --no-cache; then
        echo -e "${RED}Build failed! Please fix the errors above and try again.${NC}"
        exit 1
    fi
    echo -e "${GREEN}Test build completed successfully.${NC}"
else
    if [ "$REBUILD" = true ]; then
        echo -e "${YELLOW}Rebuilding containers...${NC}"
        if ! docker compose $COMPOSE_FILES build; then
            echo -e "${RED}Build failed! Please fix the errors above and try again.${NC}"
            exit 1
        fi
    elif [ "$PRODUCTION_MODE" = true ]; then
        echo -e "${YELLOW}Pulling published image...${NC}"
        if ! docker compose $COMPOSE_FILES pull; then
            echo -e "${RED}Pull failed! Please fix the errors above and try again.${NC}"
            exit 1
        fi
    fi

    if [ "$DETACHED" = true ]; then
        echo -e "${YELLOW}Starting Podly in detached mode...${NC}"
        docker compose $COMPOSE_FILES up -d --no-build
        echo -e "${GREEN}Podly is running in the background.${NC}"
        echo -e "${GREEN}Application: http://localhost:5001${NC}"
    else
        echo -e "${YELLOW}Starting Podly...${NC}"
        echo -e "${GREEN}Application will be available at: http://localhost:5001${NC}"
        docker compose $COMPOSE_FILES up --no-build
    fi
fi
