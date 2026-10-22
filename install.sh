#!/bin/bash
# 一键安装到 CodeBuddy / WorkBuddy 的 skill 目录
# 用法：bash install.sh
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
NAME="laowei-kit"
DEST="${1:-$HOME/.workbuddy/skills/$NAME}"

mkdir -p "$(dirname "$DEST")"
if [ -d "$DEST" ]; then
  echo "已存在 $DEST，将覆盖更新..."
  rm -rf "$DEST"
fi
cp -r "$SRC" "$DEST"
echo "✅ 已安装到：$DEST"
echo ""
echo "验证："
echo "  python3 $DEST/scripts/test_calc.py"
echo "  python3 $DEST/scripts/calc.py --demo"
