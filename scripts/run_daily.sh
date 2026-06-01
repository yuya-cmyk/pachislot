#!/bin/bash
# パチスロ日次収集ジョブ（22:50 launchd から実行）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$SCRIPT_DIR/logs/cron_collect_$(date '+%Y%m%d').log"
LOCKFILE=/tmp/pachislot_collect.lock

exec >> "$LOG" 2>&1

echo "=== 収集開始 $(date '+%Y-%m-%d %H:%M:%S') ==="

# 多重起動防止
if [[ -f "$LOCKFILE" ]]; then
    OLD_PID=$(cut -d: -f1 "$LOCKFILE" 2>/dev/null || echo "")
    LOCK_TIME=$(cut -d: -f2 "$LOCKFILE" 2>/dev/null || echo "0")
    AGE=$(( $(date +%s) - ${LOCK_TIME:-0} ))
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null && (( AGE < 7200 )); then
        echo "別プロセスが実行中 (PID=$OLD_PID 経過${AGE}秒)、スキップ"
        exit 0
    fi
fi
echo "$$:$(date +%s)" > "$LOCKFILE"
trap "rm -f $LOCKFILE" EXIT

# ネットワーク疎通確認（最大30分待機、Wi-Fi再接続を考慮）
CONNECTED=0
for i in {1..36}; do
    if ping -c 1 -W 3000 papimo.jp > /dev/null 2>&1; then
        CONNECTED=1
        break
    fi
    echo "ネットワーク未接続 (試行 $i/36)、50秒待機..."
    sleep 50
done
if [[ $CONNECTED -eq 0 ]]; then
    echo "30分待機後もネットワーク接続に失敗。終了します。"
    exit 1
fi
echo "ネットワーク接続確認 (試行 $i 回目)"

# 翌日の起床スケジュール設定（22:40 に起床してネットワーク安定化）
WAKE_DATE=$(date -v+1d "+%m/%d/%Y")
if ! pmset -g sched | grep -q "22:40:00"; then
    sudo pmset schedule wake "${WAKE_DATE} 22:40:00" 2>/dev/null || true
    echo "pmset wake 設定: ${WAKE_DATE} 22:40:00"
fi

# 収集実行
# 22:50 起動予定が日付跨ぎで遅延した場合（00:00〜09:59）は前日データを収集
HOUR=$(date '+%H')
if (( 10#$HOUR < 10 )); then
    TARGET_DATE=$(date -v-1d '+%Y%m%d')
    echo "日付跨ぎ検出: 前日データを収集 (TARGET_DATE=$TARGET_DATE)"
else
    TARGET_DATE=$(date '+%Y%m%d')
fi

source "$SCRIPT_DIR/venv/bin/activate"
caffeinate -i python -u "$SCRIPT_DIR/main.py" --date "$TARGET_DATE"

echo "=== 完了 $(date '+%Y-%m-%d %H:%M:%S') ==="
