#!/bin/bash
# 一键安装视频情报局运行环境
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 没找到 python3，请先安装 Python 3.10 或更高版本。"
  echo "        https://www.python.org/downloads/"
  exit 1
fi

echo "正在安装视频情报局运行环境，请稍候..."
echo
python3 scripts/install.py "$@"
rc=$?
if [ $rc -ne 0 ]; then
  echo
  echo "[错误] 安装失败，请把上面的信息发给作者。"
  read -r -p "按回车键关闭窗口..." _
  exit $rc
fi

echo
echo "安装完成。打开 WorkBuddy 说一句：启动视频情报局"
read -r -p "按回车键关闭窗口..." _
