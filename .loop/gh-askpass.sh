#!/bin/sh
case "$1" in
  Username*) echo "x-access-token" ;;
  Password*) printf '%s' "$GH_TOKEN" ;;
  *) printf '%s' "$GH_TOKEN" ;;
esac