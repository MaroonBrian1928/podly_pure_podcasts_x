#!/usr/bin/env bash
# Resolve the version / tag prefix used for Docker image tags in CI.
#
# Meant to be `source`d from a GitHub Actions bash step (which runs with
# `set -eo pipefail`). It reads the standard GITHUB_REF / GITHUB_REF_NAME
# env vars and the checked-out git history (so the caller must check out with
# fetch-depth: 0 to make tags available), and exports:
#
#   version  clean semver (e.g. 2.0.3) when building a released commit, else ""
#   prefix   tag prefix for per-arch images: the version when available,
#            otherwise the sanitized ref name (branch/tag)

ref_name="${GITHUB_REF_NAME//\//-}"

raw=""
if [[ "$GITHUB_REF" == refs/tags/* ]]; then
  # Direct tag push.
  raw="$GITHUB_REF_NAME"
else
  # workflow_run / branch dispatch: GITHUB_REF is a branch, so a clean version
  # only applies when a version tag sits on the checked-out commit itself
  # (the just-released commit). We deliberately do NOT fall back to the nearest
  # reachable tag, so an ad-hoc branch dispatch never republishes `latest`.
  raw="$(git tag --points-at HEAD 2>/dev/null | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+' | sort -V | tail -1 || true)"
fi

version="${raw#v}"
if [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  prefix="$version"
else
  prefix="$ref_name"
  version=""
fi
