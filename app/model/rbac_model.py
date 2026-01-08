from typing import List

from pydantic import BaseModel
#todo 角色和权限相关的请求模型，用于接口接收前端的数据

class SetRolePermsReq(BaseModel):
    perm_codes: List[str]

class SetUserRolesReq(BaseModel):
    role_codes: List[str]