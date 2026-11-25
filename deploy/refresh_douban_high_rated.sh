#!/bin/sh
set -eu

ROOT="/volume1/docker/moviehub"
cd "$ROOT"

if [ "$(pwd -P)" != "$ROOT" ]; then
  echo "拒绝执行：必须从生产目录 $ROOT 运行" >&2
  exit 1
fi

SNAPSHOT_DATE="${1:-$(date +%F)}"
case "$SNAPSHOT_DATE" in
  [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
  *) echo "日期格式必须为 YYYY-MM-DD" >&2; exit 2 ;;
esac

OUTPUT="/tmp/moviehub-douban-high-rated-$SNAPSHOT_DATE.json"

echo "将尝试按豆瓣 robots.txt 规则采集最多 100 条“豆瓣高分”公开榜单。"
echo "如果 robots.txt 不允许或豆瓣返回 403/429，将立即停止，不绕过限制。"
echo "快照日期：$SNAPSHOT_DATE"

docker compose exec -T moviehub sh -lc "
  python -m scripts.collect_douban_tagged_chart \
    --chart high-rated \
    --date '$SNAPSHOT_DATE' \
    --output '$OUTPUT' \
    --max-items 100 \
    --overwrite &&
  python -m scripts.db_backup backup &&
  python -m scripts.import_chart --input '$OUTPUT' &&
  rm -f '$OUTPUT'
"

echo "[SUCCESS] 豆瓣高分榜快照已导入；未重启任何容器。"
