
class Role:
    ROLE_PUBLIC = 'public',
    ROLE_HR = 'hr',
    ROLE_IT = 'it',
    ROLE_ADMIN = 'admin',



class Permission:
    # // leave
    PERM_LEAVE_APPLY = 'leave.apply'
    PERM_LEAVE_VIEW_SELF = 'leave.view_self'
    PERM_LEAVE_VIEW_ALL = 'leave.view_all'
    PERM_LEAVE_CANCEL = 'leave.cancel'
    PERM_LEAVE_MODIFY = 'leave.modify'
    PERM_LEAVE_APPROVE = 'leave.approve'
    PERM_LEAVE_REJECT = 'leave.reject'

    # // kb
    PERM_KB_VIEW_PUBLIC = 'kb.view_public'
    PERM_KB_VIEW_INTERNAL = 'kb.view_internal'
    PERM_KB_MANAGE_DOCS = 'kb.manage_docs'

    # // ticket
    PERM_TICKET_CREATE = 'ticket.create'
    PERM_TICKET_VIEW_SELF = 'ticket.view_self'
    PERM_TICKET_VIEW_ALL = 'ticket.view_all'
    PERM_TICKET_CLOSE = 'ticket.close'

    # // system
    PERM_SYSTEM_MANAGE_USERS = 'system.manage_users'
    PERM_SYSTEM_MANAGE_ROLES = 'system.manage_roles'