import os
import pymysql
from contextlib import contextmanager
from dbutils.pooled_db import PooledDB

# todo 实现了一个完整的 请假管理数据库层（Leave Requests DB Layer）

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "ldm")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "123456")
MYSQL_DB = os.getenv("MYSQL_DB", "enterprise_kb")

# -----------------------------
# 创建全局数据库连接池（关键）
# -----------------------------
POOL = PooledDB(
    creator=pymysql,          # 使用的 DB API
    maxconnections=10,        # 连接池最大连接数（很重要）
    mincached=2,              # 启动时创建的空闲连接
    maxcached=5,              # 连接池中最多空闲连接
    blocking=True,            # 连接耗尽时是否阻塞等待
    host=MYSQL_HOST,
    port=MYSQL_PORT,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DB,
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    autocommit=True,
)

# -----------------------------
# 获取连接（从池中取）
# -----------------------------
@contextmanager
def get_conn():
    conn = POOL.connection()  # 不是新建，是“借用”
    try:
        yield conn
    finally:
        conn.close()          # ⚠️ 不是关闭数据库，而是“归还连接”




