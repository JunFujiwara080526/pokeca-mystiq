#!/bin/bash
cd "$(dirname "$0")"
if [ -f mystiq.pid ]; then
  kill $(cat mystiq.pid) 2>/dev/null && echo "Mystiq サーバーを停止しました。" || echo "サーバーは既に停止しています。"
  rm -f mystiq.pid
else
  pkill -f "python3.*server.py" 2>/dev/null && echo "Mystiq サーバーを停止しました。" || echo "停止対象のサーバーは見つかりませんでした。"
fi
