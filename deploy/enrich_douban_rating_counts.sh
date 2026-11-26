#!/bin/sh
set -eu

ROOT="/volume1/docker/moviehub"
cd "$ROOT"

if [ "$(pwd -P)" != "$ROOT" ]; then
  echo "拒绝执行：必须从生产目录 $ROOT 运行" >&2
  exit 1
fi

MODE="${1:---dry-run}"
case "$MODE" in
  --dry-run|--apply) ;;
  *) echo "用法：$0 [--dry-run|--apply]" >&2; exit 2 ;;
esac

echo "将检查年度榜单中已有豆瓣条目 ID 的记录。"
echo "只读取 m.douban.com 公共移动端详情 API；先检查 robots.txt。"
echo "每条请求间隔至少 2.5 秒；遇到 401/403/429 或 robots 禁止立即停止。"
echo "默认 dry-run，不写数据库。"

docker compose build moviehub
docker compose run --rm --no-deps -T moviehub \
  python -m scripts.enrich_douban_rating_counts "$MODE"
