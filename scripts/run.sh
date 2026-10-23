#!/usr/bin/env bash
# 视频情报局统一入口。依次探测运行环境，找到就用。
# 显式指定解释器：export VDI_PYTHON=/path/to/python
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYEXE="${VDI_PYTHON:-}"
if [ -z "$PYEXE" ]; then
  for cand in \
    "$HOME/.workbuddy/vdi-runtime/bin/python" \
    "$HERE/../.venv/bin/python" \
    "$HOME/.workbuddy/binaries/python/envs/douyin312/bin/python"
  do
    if [ -x "$cand" ]; then PYEXE="$cand"; break; fi
  done
fi

if [ -z "$PYEXE" ]; then
  echo "[错误] 没找到运行环境。请先执行：python3 \"$HERE/install.py\"" >&2
  exit 1
fi

export PYTHONIOENCODING=utf-8
exec "$PYEXE" "$HERE/runner.py" "$@"
