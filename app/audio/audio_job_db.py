from __future__ import annotations

from typing import Optional, Any
from app.db.mysql import get_conn

#todo 你这一组函数是 音频任务管理模块，主要操作 audio_jobs 表，用于 创建任务、绑定 Celery 任务、更新状态、取消任务以及查询任务信息。
def create_job(
    job_id: str,
    audio_id: str,
    *,
    overwrite: bool = False,
    delete_old_file: bool = False,
    old_stored_path: str | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audio_jobs (job_id, audio_id, status, progress, overwrite, delete_old_file, old_stored_path) "
                "VALUES (%s,%s,'queued',0,%s,%s,%s)",
                (job_id, audio_id, int(overwrite), int(delete_old_file), old_stored_path),
            )


def bind_task(job_id: str, celery_task_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE audio_jobs SET celery_task_id=%s WHERE job_id=%s",
                (celery_task_id, job_id),
            )


def update_job(job_id: str, *, status: str | None = None, progress: int | None = None, message: str | None = None) -> None:
    fields = []
    args: list[Any] = []
    if status is not None:
        fields.append("status=%s")
        args.append(status)
    if progress is not None:
        fields.append("progress=%s")
        args.append(int(progress))
    if message is not None:
        fields.append("message=%s")
        args.append(message)
    if not fields:
        return
    sql = f"UPDATE audio_jobs SET {', '.join(fields)} WHERE job_id=%s"
    args.append(job_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(args))


def get_job(job_id: str) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT job_id, audio_id, celery_task_id, status, progress, message, cancel_requested, overwrite, "
                "delete_old_file, old_stored_path, cancelled_at, created_at, updated_at "
                "FROM audio_jobs WHERE job_id=%s LIMIT 1",
                (job_id,),
            )
            return cur.fetchone()


def request_cancel(job_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE audio_jobs SET cancel_requested=1, message='cancel requested' WHERE job_id=%s",
                (job_id,),
            )
            return cur.rowcount > 0

                                                                                                        #todo 它从数据库里查这个任务有没有被标记为“请求取消”，并把各种不确定结果统一收敛成一个 True / False。
def is_cancel_requested(job_id: str) -> bool:
    with get_conn() as conn:                                                                            #todo 👉 获取数据库连接with 保证异常时也会正确关闭防止连接泄漏
        with conn.cursor() as cur:                                                                      #todo cursor 的存在是为了：隔离 DB 细节，控制资源生命周期，保证并发安全，Connection 是“通道”，Cursor 是“操作句柄”。所有 SQL 都必须通过 Cursor。
            cur.execute("SELECT cancel_requested FROM audio_jobs WHERE job_id=%s LIMIT 1", (job_id,))   #todo 在 audio_jobs 表中，按固定规则查找指定 job_id 的记录，只取它的 cancel_requested 状态最多返回一条。%s 不是规定“查找范围”，而是规定“输入只能是值，不能参与查找规则本身”。
            row = cur.fetchone()                                                                        #todo fetchone() 不是“拿一行数据”，而是“声明：我只允许一行结果进入我的程序”。它是一个：数据量边界语义边界责任边界
            return bool(row and int(row.get("cancel_requested", 0)) == 1)                               #todo 你在函数里返回的那个 bool，就是在做“边界净化 + 类型收口 + 语义隔离”,函数的名字定义了它的语义，返回值必须 100% 对齐这个语义。多出来的含义，就是污染。

                                                                                                        #todo %s：值不能进入语义
                                                                                                        # SQL 固定：输入不能改变意图
                                                                                                        # LIMIT 1：结果规模固定       LIMIT 1 决定“数据库最多给多少”，
                                                                                                        # fetchone()：消费规模固定    fetchone() 决定“程序只拿多少”。
                                                                                                        # bool(...)：业务语义固定
                                                                                                        # 这是一整条 “防扩散链”

def mark_cancelled(job_id: str, message: str = "cancelled") -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE audio_jobs SET status='cancelled', progress=100, message=%s, cancelled_at=NOW() WHERE job_id=%s",
                (message, job_id),
            )


def get_job_flags(job_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT overwrite, delete_old_file, old_stored_path, cancel_requested FROM audio_jobs WHERE job_id=%s LIMIT 1",
                (job_id,),
            )
            return cur.fetchone() or {}
