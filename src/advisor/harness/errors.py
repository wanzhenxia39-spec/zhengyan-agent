class HarnessDenied(Exception):
    """越权、出域违规或安全检查不可用：直接拒绝。"""


class BudgetExceeded(Exception):
    """预算或时限耗尽：只降级深度，不放松质量门控。"""


class ApprovalRequired(Exception):
    """需要人工确认的调用。"""


class SkillFailed(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class TaskCancelled(Exception):
    """任务被取消或授权被撤销：立即停止，不重放外部动作。"""
