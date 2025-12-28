from fastapi import HTTPException
from app.db.kb_db import get_allowed_visibilities


def normalize_visibility(v: str) -> str:
    # 用于校验可见性字符串是否合理
    v = (v or "").strip().lower()
    if v not in get_allowed_visibilities():  # 此处的ALLOWED_VISIBILITIES要去数据库里查
        # 这里也可以换成一个数据库的select，用v去数据库里查询
        raise HTTPException(status_code=400, detail=f"invalid visibility: {v}")
    return v
