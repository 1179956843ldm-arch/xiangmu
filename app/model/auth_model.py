from typing import Optional

from pydantic import BaseModel, EmailStr
#todo 你这段代码是 用户注册/登录相关的 Pydantic 模型定义，主要用于请求验证和响应序列化。

class RegisterReq(BaseModel):
    username: str
    password: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None

class LoginReq(BaseModel):
    username: str
    password: str

class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserInDB(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool
    is_super_admin: bool