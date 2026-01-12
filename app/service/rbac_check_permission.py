from app.model.auth_model import UserInDB
from app.service.rbac_service import check_permission

class KBPermissions:
    KB_MANAGE_DOCS  = "kb.manage_docs"
class LeavePermission:
    LEAVE_APPROVE = "leave.approve"

def require_kb_manage_docs(user: UserInDB) -> None:
    check_permission(user, KBPermissions.KB_MANAGE_DOCS)