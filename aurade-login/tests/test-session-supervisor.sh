#!/bin/bash
root_dir="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
exec /usr/bin/bash "${root_dir}/test-session-supervisor.sh" "$@"
