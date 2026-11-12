#!/bin/bash
# Brings this Mac to a released version, after Deploy has migrated the hosted database:
#   ops/upgrade.sh            the latest release (vX.Y.Z)
#   ops/upgrade.sh v0.2.0     a given one
# Installs the `lifter` command of that version (the sync stops on "schema out of date" with an
# older one), then the jobs' scripts of the same version, from a throwaway clone of its tag: what
# runs never depends on the branch checked out here. The dependencies are the ones of the tag's
# lock, and the tag must be on main.
set -euo pipefail
REPO="https://github.com/gabrielkpo/lifter"

version="${1:-}"
if [[ -z "$version" ]]; then
  version=$(git ls-remote --tags --refs "$REPO" 'v*' | sed 's#.*refs/tags/##' | sort -V | tail -1)
fi
if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "no release to install (got '${version}'); versions look like v1.2.3" >&2
  exit 2
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git -c advice.detachedHead=false clone --quiet --branch "$version" "$REPO" "$work/lifter"
# A release tag is cut from main by release-please: refuse a tag that main does not hold.
if ! git -C "$work/lifter" merge-base --is-ancestor "$version" origin/main; then
  echo "$version is not on main: refused" >&2
  exit 2
fi
# The versions CI tested: the tag's lock, as constraints (uv tool install does not read uv.lock).
(cd "$work/lifter" && uv export --frozen --no-dev --no-emit-project --no-hashes --quiet \
  --output-file "$work/constraints.txt")
uv tool install --force --constraints "$work/constraints.txt" "$work/lifter"
bash "$work/lifter/ops/install.sh"
echo "this Mac runs $version"
