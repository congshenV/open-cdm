"""CloudDM console 出向调用（JWT 透传）。

dmops 回调 console 的页面接口（/api/entry/**）：JWT 来自用户浏览器请求的
Cookie（DmOpsProxyController 转发透传），仅内存使用不落库不打印。
回调时走 `dm_jwt_token` header（console JwtService.verify 的取值顺序：
query 参数 → header → Cookie，header 免拼 Cookie 语义）。
"""
