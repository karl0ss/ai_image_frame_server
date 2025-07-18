#!/bin/bash
set -ex

# Check if an argument is provided
if [ -z "$1" ]; then
  echo "Usage: $0 <part>"
  echo "Example: $0 patch"
  exit 1
fi

PART=$1

# Bump the version
bump-my-version bump $PART

# Push the changes
git push
git push origin --tags