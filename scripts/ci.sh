#!/bin/bash
set -Eeuo pipefail

# Parse command line arguments
RUN_INTEGRATION=false
RUN_WRITER_CONTAINER=false
RUN_WRITER_ROLLBACK=false
for arg in "$@"; do
    if [ "$arg" = "--int" ]; then
        RUN_INTEGRATION=true
    elif [ "$arg" = "--writer-container" ]; then
        RUN_WRITER_CONTAINER=true
    elif [ "$arg" = "--writer-rollback" ]; then
        RUN_WRITER_ROLLBACK=true
    fi
done

# ensure dependencies are installed and are always up to date
echo '============================================================='
echo "Running 'uv sync --extra dev'"
echo '============================================================='
uv sync --extra dev
echo '============================================================='
echo "Running 'uv run ruff format .'"
echo '============================================================='
uv run ruff format .
echo '============================================================='
echo "Running 'uv run ruff check --fix .'"
echo '============================================================='
uv run ruff check --fix .

# type check
echo '============================================================='
echo "Running 'uv run ty check'"
echo '============================================================='
uv run ty check

echo '============================================================='
echo "Checking startup and health shell syntax"
echo '============================================================='
bash -n scripts/start_services.sh scripts/healthcheck.sh scripts/test_rust_writer_container.sh scripts/test_rust_writer_rollback.sh

# Build the Rust executables used by writer differential tests before pytest.
# Reuse only these binaries during tests so the Python and Rust paths execute
# against the same current source revision.
if [ -f rust/Cargo.toml ]; then
    echo '============================================================='
    echo "Building Rust binaries required by parity tests"
    echo '============================================================='
    mise exec -- cargo build \
        --manifest-path rust/Cargo.toml \
        --bin podly_writer \
        --bin podly_tools
    export PODLY_RUST_WRITER_BIN="${PWD}/rust/target/debug/podly_writer"
    export PODLY_RUST_TOOLS_BIN="${PWD}/rust/target/debug/podly_tools"
fi

# run tests
echo '============================================================='
echo "Running 'uv run pytest --disable-warnings'"
echo '============================================================='
uv run pytest --disable-warnings

if [ -f rust/Cargo.toml ]; then
    echo '============================================================='
    echo "Running Rust checks"
    echo '============================================================='
    (
        cd rust || exit 1
        cargo fmt --check
        cargo clippy -- -D warnings
        cargo test
    )
fi

# The live Python writer API and Rust implementation must remain parity-complete.
echo '============================================================='
echo "Running 'uv run python scripts/check_writer_registry.py'"
echo '============================================================='
uv run python scripts/check_writer_registry.py

# Run integration tests only if --int flag is provided
if [ "$RUN_INTEGRATION" = true ]; then
    echo '============================================================='
    echo "Running integration workflow checks..."
    echo '============================================================='
    uv run python scripts/check_integration_workflow.py
fi

# This mode builds a uniquely tagged image and mounts only fresh named volumes.
# It never targets the running localhost integration service used by --int.
if [ "$RUN_WRITER_CONTAINER" = true ]; then
    echo '============================================================='
    echo "Running isolated Rust writer container lifecycle checks"
    echo '============================================================='
    ./scripts/test_rust_writer_container.sh
fi

# This mode rehearses writer rollback in a fresh, isolated named Docker volume.
if [ "$RUN_WRITER_ROLLBACK" = true ]; then
    echo '============================================================='
    echo "Running isolated Rust writer rollback rehearsal"
    echo '============================================================='
    ./scripts/test_rust_writer_rollback.sh
fi
