#!/bin/bash
# Mystiq 謎解きシステム 起動スクリプト
cd "$(dirname "$0")"
PORT="${MYSTIQ_PORT:-8080}"
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")

echo "==============================================="
echo "   Mystiq 謎解き回答・進行システム"
echo "==============================================="
echo ""
echo "サーバー起動中..."
python3 server.py &
PID=$!
echo $PID > mystiq.pid

sleep 1
if ! kill -0 $PID 2>/dev/null; then
  echo "起動に失敗しました。ポート ${PORT} が使用中の可能性があります。"
  exit 1
fi

echo ""
echo "✔ 起動完了！ブラウザで以下を開いてください："
echo ""
echo "  [このパソコンから]"
echo "    http://localhost:${PORT}/"
echo ""
echo "  [同じWi-Fiにつながっているスマホから]"
echo "    http://${IP}:${PORT}/"
echo ""
  echo "  画面一覧:"
  echo "    回答画面    : http://localhost:${PORT}/index.html"
  echo "    ランキング  : http://localhost:${PORT}/ranking.html"
  echo "    実況ボード  : http://localhost:${PORT}/screen.html   ★プロジェクター用"
  echo "    管理画面    : http://localhost:${PORT}/admin.html"
  echo ""
  if [ -n "$ADMIN_PASSWORD" ]; then
    echo "  [管理者パスワード] 環境変数 ADMIN_PASSWORD で設定済み"
  elif [ -f data/admin_password.txt ]; then
    echo "  [管理者パスワード] $(cat data/admin_password.txt)"
  fi
  echo ""
  echo "終了するには Ctrl+C を押してください。"
  echo "==============================================="

trap 'echo ""; echo "サーバーを停止しています..."; kill $PID 2>/dev/null; rm -f mystiq.pid; exit 0' INT TERM
wait $PID
