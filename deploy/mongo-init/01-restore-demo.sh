#!/bin/bash
# mongo 官方镜像只在数据卷为空的首次启动时执行本目录脚本：导入演示数据（不含个人约束 profiles）。
# 已有数据的卷不会被覆盖。想重置为演示数据：docker compose down -v && docker compose up -d
set -e
ARCHIVE=/docker-entrypoint-initdb.d/demo-data.archive.gz
if [ -f "$ARCHIVE" ]; then
  echo "[advisor] 导入演示数据 ..."
  mongorestore --quiet --gzip --archive="$ARCHIVE" --nsInclude='advisor.*'
  echo "[advisor] 演示数据导入完成"
fi
