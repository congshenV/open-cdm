"""业务异常。

service 层抛出 ``ApiError``，由 main.py 注册的处理器统一转换为响应体，
避免每个接口重复写 try/except。
"""


class ApiError(Exception):
    """可直接映射为统一响应体的业务异常。"""

    def __init__(self, code: int, user_message: str, message: str = '', http_status: int = 400):
        super().__init__(message or user_message)
        self.code = code
        self.user_message = user_message
        self.message = message or user_message
        self.http_status = http_status
