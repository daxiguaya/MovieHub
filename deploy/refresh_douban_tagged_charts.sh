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

echo "将按豆瓣 robots.txt 规则依次采集实时热门和高分榜。"
echo "两份数据都采集成功后才会备份并在同一事务中导入。"
echo "如遇 robots.txt 禁止、403 或 429，将停止且不写数据库。"
echo "快照日期：$SNAPSHOT_DATE"

docker compose exec -T moviehub \
  python -m scripts.refresh_douban_tagged_charts \
  --date "$SNAPSHOT_DATE" \
  --max-items 100

echo "[SUCCESS] 豆瓣实时热门和高分榜已完成原子刷新；未重启任何容器。"
