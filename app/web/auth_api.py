from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header, status

from app.db.auth_db import get_user_by_username, create_user, update_last_login
from app.model.auth_model import UserInDB, RegisterReq, TokenResp, LoginReq
from app.service.auth_service import verify_password, create_access_token, decode_token

auth_router = APIRouter(prefix="/auth", tags=["auth"])
# ---------------- Dependencies ----------------

def get_current_user(authorization: str | None = Header(default=None)) -> UserInDB:
    #从 HTTP 请求里解析 Bearer Token，校验身份，并把“当前登录用户”解析成一个后端可用的用户对象。 current_user请求用户   Authorization → 授权 / 许可 / 批准
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    u = get_user_by_username(username)
    if not u or not u.get("is_active"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")

    return UserInDB(
        id=int(u["id"]),
        username=u["username"],
        email=u.get("email"),
        phone=u.get("phone"),
        full_name=u.get("full_name"),
        is_active=bool(u["is_active"]),
        is_super_admin=bool(u["is_super_admin"]),
    )

def get_current_user_optional(authorization: str | None = Header(default=None)) -> UserInDB | None:
    #核心作用：允许接口 支持登录用户和匿名访问
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        return None
    try:
        return get_current_user(authorization=authorization)
    except HTTPException:
        return None

# ---------------- Routes ----------------

@auth_router.post("/register", response_model=UserInDB)

def register(req: RegisterReq):
    # 用户注册接口
    if get_user_by_username(req.username):
        raise HTTPException(status_code=400, detail="username already exists")
    u = create_user(req)
    return UserInDB(
        id=int(u["id"]),
        username=u["username"],
        email=u.get("email"),
        phone=u.get("phone"),
        full_name=u.get("full_name"),
        is_active=bool(u["is_active"]),
        is_super_admin=bool(u["is_super_admin"]),
    )

@auth_router.post("/login", response_model=TokenResp)
def login(req: LoginReq):
    #登录接口
    u = get_user_by_username(req.username)
    if not u:
        raise HTTPException(status_code=401, detail="bad credentials")

    if not verify_password(req.password, u["password_hash"]):
        raise HTTPException(status_code=401, detail="bad credentials")

    if not u.get("is_active"):
        raise HTTPException(status_code=403, detail="user disabled")

    update_last_login(int(u["id"]))
    token = create_access_token({"sub": u["username"], "uid": int(u["id"])})
    return TokenResp(access_token=token)

@auth_router.get("/me", response_model=UserInDB)
def me(current_user: UserInDB = Depends(get_current_user)):
    #获取当前登录用户信息接口
    return current_user
