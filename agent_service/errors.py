class AgentRunError(Exception):
    def __init__(self, code, message, *, stage="多 Agent 编排", retryable=False, cause=None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.cause = cause


def error_payload(error):
    if isinstance(error, AgentRunError):
        return {
            "code": error.code,
            "message": str(error),
            "stage": error.stage,
            "retryable": error.retryable,
        }
    return {
        "code": "AGENT_RUN_FAILED",
        "message": "多 Agent 分析执行失败。",
        "stage": "多 Agent 编排",
        "retryable": True,
    }

