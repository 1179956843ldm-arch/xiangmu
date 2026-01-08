import re
#todo 从文本中提取 请假单号（leave ID）

class LeaveTools:
    @staticmethod
    def _extract_leave_id(text: str) -> str | None:
        if not text:
            return None
        m = re.search(r"\bLV-[0-9a-fA-F]{6,12}\b", text)
        return m.group(0) if m else None