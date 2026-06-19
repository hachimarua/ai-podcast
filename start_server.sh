#!/bin/bash
# AI News & Learning System - Local Podcast Server Runner

# スクリプトの親ディレクトリに移動
cd "$(dirname "$0")"

# ローカルIPの取得 (Pythonのワンライナーで安全に抽出)
LOCAL_IP=$(python3 -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('10.254.254.254', 1)); print(s.getsockname()[0]); s.close()")
PORT=8000

echo "=================================================="
echo "   AI News & Learning Podcast Server"
echo "=================================================="
echo "Starting local HTTP server on port $PORT..."
echo ""
echo "👉 iPhoneの「ポッドキャスト」アプリに登録するURL:"
echo "   http://$LOCAL_IP:$PORT/podcast.xml"
echo "=================================================="
echo "Ctrl+C でサーバーを停止できます。"
echo ""

# Python 簡易サーバーの起動
python3 -m http.server $PORT
