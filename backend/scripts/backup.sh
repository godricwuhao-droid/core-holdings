#!/usr/bin/env bash
#
# 蜂云产品及服务平台 —— 每日数据备份（DB + uploads + JWT 密钥）
#
# 备份内容：
#   1. core_holdings.db   —— SQLite 在线备份 API 导出（服务运行中不停机、不产生半写文件）
#   2. uploads.tar.gz     —— 合同文件 / 交付物附件（散列名，与 DB 引用强绑定）
#   3. .jwt_secret        —— JWT 签名密钥（保证恢复后已签发 token 仍有效）
#   4. manifest.txt       —— 校验值、行数、恢复步骤
#
# 两个必须遵守的约束（都是踩过的坑）：
#   A. **先 DB 后 uploads**：反序会出现「DB 引用了备份之后才上传的文件 → 恢复后附件缺失」；
#      按本顺序最坏只是多备几个未被引用的孤儿文件（无害）。
#   B. **先本地生成、再搬运到目标**：SQLite 的 POSIX 文件锁在 NFS 上不可靠
#      （直接 connect 到 NFS 会 `unable to open database file`），故整个备份在本地临时目录
#      完成并校验通过后，再整目录 cp 到 NFS；搬运后逐个文件比对 md5。
#
# 用法：
#   ./backup.sh                          # 正常备份（目标 /backup/core-holdings）
#   BACKUP_ROOT=/data/backup/x ./backup.sh   # 覆盖目标目录
#   KEEP_DAYS=7 ./backup.sh              # 覆盖保留天数（默认 30）
#
set -euo pipefail

# cron 环境的 PATH 极简（/usr/bin:/bin），显式固定，保证 tar/cp/find/df 等都能找到
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

SRC_DIR="${SRC_DIR:-/data/core-holdings/backend}"
BACKUP_ROOT="${BACKUP_ROOT:-/backup/core-holdings}"
KEEP_DAYS="${KEEP_DAYS:-30}"
DB_NAME="core_holdings.db"

PY="${PY:-/usr/bin/python3}"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$TS"
WORK="${WORK_DIR:-${TMPDIR:-/tmp}/ch-backup-$TS}"

# NFS hard mount 下读写会无限重试，所有落盘动作一律加超时，防止 cron 任务堆积
IO_TIMEOUT="${IO_TIMEOUT:-300}"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*"; }

# du 在 NFS 上属性缓存不可靠（刚写完常返回 512 / 1.0K），日志体积改用 stat 字节数汇总
human_bytes() {
  timeout 60 find "$1" -type f -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {
    if (s < 1024) printf "%d B", s
    else if (s < 1048576) printf "%.0f K", s/1024
    else printf "%.1f M", s/1048576
  }'
}

cleanup_on_error() {
  local code=$?
  echo "[$(ts)] FAIL 备份失败（exit=$code）"
  if [[ -n "${WORK:-}" && -d "$WORK" ]]; then
    timeout 60 rm -rf "$WORK" 2>/dev/null || true
  fi
  if [[ -n "${DEST:-}" && -d "$DEST" ]]; then
    echo "[$(ts)] 清理半成品：$DEST"
    timeout 60 rm -rf "$DEST" 2>/dev/null || true
  fi
  exit "$code"
}
trap cleanup_on_error ERR

# ---------------- 1. 源预检 ----------------
log "START 源=$SRC_DIR 目标=$BACKUP_ROOT 保留=${KEEP_DAYS}天"
[[ -f "$SRC_DIR/$DB_NAME" ]] || { log "FAIL 数据库不存在：$SRC_DIR/$DB_NAME"; exit 2; }
[[ -d "$SRC_DIR/uploads" ]] || { log "FAIL 附件目录不存在：$SRC_DIR/uploads"; exit 2; }

SRC_SIZE_KB=$(du -sk "$SRC_DIR/$DB_NAME" "$SRC_DIR/uploads" | awk '{s+=$1} END {print s}')

# ---------------- 2. 目标预检（目录 + 可写探测 + 空间） ----------------
timeout 30 mkdir -p "$BACKUP_ROOT" 2>/dev/null || { log "FAIL 备份根目录创建失败：$BACKUP_ROOT（存储不可达？）"; exit 4; }
FREE_KB=$(timeout 30 df -Pk "$BACKUP_ROOT" 2>/dev/null | awk 'NR==2 {print $4}')
if [[ -z "${FREE_KB:-}" || ! "$FREE_KB" =~ ^[0-9]+$ ]]; then
  log "FAIL 无法获取目标可用空间：$BACKUP_ROOT（挂载异常或不可达）"
  exit 3
fi
# 单份备份约为源数据的 1.5 倍（tar 压缩），要求剩余空间 ≥ 3 倍源数据
if (( FREE_KB < SRC_SIZE_KB * 3 )); then
  log "FAIL 磁盘空间不足：可用 ${FREE_KB}KB，需 ≥ $((SRC_SIZE_KB * 3))KB"
  exit 3
fi
log "目标可用 ${FREE_KB}KB，源数据 ${SRC_SIZE_KB}KB"

# 写入-回读探测：网络盘可能 df 正常、写入返回成功但实际 IO 失败（NFS stale）
PROBE="$BACKUP_ROOT/.probe-$TS"
if ! timeout 30 bash -c "echo '$TS' > '$PROBE' && [ \"\$(cat '$PROBE')\" = '$TS' ]" 2>/dev/null; then
  log "FAIL 目标目录不可写或写入后无法回读：$BACKUP_ROOT"
  log "      常见原因：NFS stale / 挂载异常 / 权限不足 —— 请检查 mount 或改用本地目录"
  timeout 30 rm -f "$PROBE" 2>/dev/null || true
  exit 5
fi
timeout 30 rm -f "$PROBE" 2>/dev/null || true
log "目标读写探测通过"

# ---------------- 3. 本地工作区（SQLite 不能在 NFS 上建库，见文件头约束 B） ----------------
timeout 30 mkdir -p "$WORK" || { log "FAIL 本地工作区创建失败：$WORK"; exit 4; }
log "本地工作区：$WORK"

# ---------------- 4. 备份数据库（在线备份 API，写本地） ----------------
# 服务运行中 journal_mode=delete，直接 cp 可能拿到半写状态文件，故统一走 sqlite3.backup()
timeout "$IO_TIMEOUT" "$PY" - "$SRC_DIR/$DB_NAME" "$WORK/$DB_NAME" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
try:
    src.backup(dst)
finally:
    dst.close(); src.close()
PY
log "数据库已备份：$DB_NAME（$(du -h "$WORK/$DB_NAME" | cut -f1)）"

# ---------------- 5. 备份附件（必须在 DB 之后） ----------------
timeout "$IO_TIMEOUT" tar -czf "$WORK/uploads.tar.gz" -C "$SRC_DIR" uploads
UPLOADS_TAR_COUNT=$(timeout 120 tar -tzf "$WORK/uploads.tar.gz" | grep -vc '/$' || true)
log "附件已打包：uploads.tar.gz（$(du -h "$WORK/uploads.tar.gz" | cut -f1)，$UPLOADS_TAR_COUNT 个文件）"

# ---------------- 6. 备份 JWT 密钥 ----------------
if [[ -f "$SRC_DIR/.jwt_secret" ]]; then
  timeout 30 cp -a "$SRC_DIR/.jwt_secret" "$WORK/.jwt_secret"
  log "密钥已备份：.jwt_secret"
else
  log "WARN 未找到 .jwt_secret（跳过；恢复后已登录会话将失效）"
fi

# ---------------- 7. 校验（全部在本地工作区，避免 NFS 抖动干扰） ----------------
# 7.1 完整性 + 表集合 + 关键表行数（与源库实时比对）
timeout "$IO_TIMEOUT" "$PY" - "$SRC_DIR/$DB_NAME" "$WORK/$DB_NAME" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)

integrity = dst.execute("pragma integrity_check").fetchone()[0]
if integrity != "ok":
    raise SystemExit(f"[CHECK] integrity_check 失败：{integrity}")

src_tables = {r[0] for r in src.execute("select name from sqlite_master where type='table'")}
dst_tables = {r[0] for r in dst.execute("select name from sqlite_master where type='table'")}
if src_tables != dst_tables:
    raise SystemExit(f"[CHECK] 表集合不一致：缺 {sorted(src_tables - dst_tables)} 多 {sorted(dst_tables - src_tables)}")
if len(dst_tables) < 15:
    raise SystemExit(f"[CHECK] 表数量异常：{len(dst_tables)} 张，疑似备份不完整")
print(f"[CHECK] integrity_check=ok，表 {len(dst_tables)} 张（与源库一致）")

tables = ["assets", "rs_items", "projects", "contracts", "project_items",
          "cart_items", "flows", "outbounds", "logs", "users", "entities", "file_meta"]
rows = []
for t in tables:
    s = src.execute(f"select count(*) from {t}").fetchone()[0]
    d = dst.execute(f"select count(*) from {t}").fetchone()[0]
    if s != d:
        raise SystemExit(f"[CHECK] 表 {t} 行数不一致：源={s} 备份={d}")
    rows.append(f"{t}={d}")
print("[CHECK] 行数一致：" + " ".join(rows))
PY

# 7.2 附件引用完整性（DB 引用 vs tar 内文件）
timeout "$IO_TIMEOUT" "$PY" - "$WORK/$DB_NAME" "$WORK/uploads.tar.gz" <<'PY'
import sqlite3, sys, tarfile
db, tgz = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
ref = set()
for (n,) in conn.execute("select storedName from file_meta"):
    if n: ref.add(n)
for (n,) in conn.execute("select contractFile from assets where contractFile is not null and contractFile<>''"):
    if n: ref.add(n)
for (n,) in conn.execute("select featureDoc from assets where featureDoc is not null and featureDoc<>''"):
    if n: ref.add(n)
for (n,) in conn.execute("select file from asset_deliverables where file is not null and file<>''"):
    if n: ref.add(n)
with tarfile.open(tgz) as tf:
    names = {n.split("uploads/", 1)[1] for n in tf.getnames() if n.startswith("uploads/") and not n.endswith("/")}
missing = sorted(ref - names)
if missing:
    raise SystemExit(f"[CHECK] 附件缺失 {len(missing)} 个，示例：{missing[:3]}")
print(f"[CHECK] 附件引用完整：DB 引用 {len(ref)} 个，tar 内 {len(names)} 个（含 {len(names - ref)} 个未被引用的孤儿文件）")
PY

# ---------------- 8. manifest ----------------
{
  echo "# 蜂云产品及服务平台 数据备份"
  echo "备份时间 : $(ts)"
  echo "源目录   : $SRC_DIR"
  echo "目标目录 : $DEST"
  echo "文件校验 :"
  ( cd "$WORK" && md5sum "$DB_NAME" uploads.tar.gz 2>/dev/null | sed 's/^/  /' )
  [[ -f "$WORK/.jwt_secret" ]] && echo "  .jwt_secret : 已备份"
  echo
  echo "## 恢复步骤（务必先停服务）"
  echo "1. 停掉 uvicorn（8000 端口）"
  echo "2. cp $DEST/$DB_NAME  $SRC_DIR/$DB_NAME"
  echo "3. tar -xzf $DEST/uploads.tar.gz -C $(dirname "$SRC_DIR")   # 还原 uploads/ 全量"
  echo "4. cp $DEST/.jwt_secret $SRC_DIR/.jwt_secret && chmod 600 $SRC_DIR/.jwt_secret"
  echo "5. 启动服务；前端刷新页面（数据来自 /api/bootstrap）"
} > "$WORK/manifest.txt"
log "manifest 已写入"

# ---------------- 9. 搬运到目标（本地 → NFS），并逐文件比对 md5 ----------------
BACKUP_SIZE=$(human_bytes "$WORK")  # 用本地工作区大小（NFS 刚写完 stat 可能返回 0）
timeout 30 mkdir -p "$DEST" || { log "FAIL 目标目录创建失败：$DEST"; exit 4; }
if ! timeout "$IO_TIMEOUT" cp -a "$WORK/." "$DEST/" 2>/dev/null; then
  log "FAIL 备份搬运失败（目标存储异常）：$DEST"
  exit 7
fi
log "已搬运到目标：$DEST（$BACKUP_SIZE）"

( cd "$WORK" && md5sum "$DB_NAME" uploads.tar.gz ) > "$WORK/.md5.local"
if ! ( cd "$DEST" && md5sum -c "$WORK/.md5.local" ) > /dev/null 2>&1; then
  log "FAIL 目标文件 md5 校验失败（写入不完整或存储异常）"
  exit 8
fi
log "目标文件 md5 校验通过"

timeout 60 rm -rf "$WORK" 2>/dev/null || true

# ---------------- 10. 清理过期备份 ----------------
DELETED=0
while IFS= read -r d; do
  timeout 120 rm -rf "$d" 2>/dev/null && { DELETED=$((DELETED + 1)); log "已删除过期备份：$(basename "$d")"; }
done < <(timeout 120 find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" 2>/dev/null | sort)
log "清理完成：删除 $DELETED 份（保留最近 ${KEEP_DAYS} 天）"

TOTAL=$(timeout 60 find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null | wc -l)
# 总体积不在此统计：NFS 属性缓存对刚写入的目录可能返回 0，需要时用 du -sh 手动查看
log "DONE 校验通过，当前共 $TOTAL 份备份（保留 ${KEEP_DAYS} 天）"
