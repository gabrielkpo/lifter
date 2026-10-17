#!/bin/bash
# Brings this Mac to a released version, after Deploy has migrated the hosted database:
#   ops/upgrade.sh            the latest release (vX.Y.Z)
#   ops/upgrade.sh v0.2.0     a given one
# Installs the `lifter` command of that version (the sync stops on "schema out of date" with an
# older one), then the jobs' scripts of the same version, from a throwaway clone of its tag: what
# runs never depends on the branch checked out here.
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

uv tool install --force "git+$REPO@$version"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$version" "$REPO" "$work/lifter"
bash "$work/lifter/ops/install.sh"
echo "this Mac runs $version"
