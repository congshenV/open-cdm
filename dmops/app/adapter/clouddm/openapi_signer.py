"""console OpenAPI AK/SK 签名（OpenApiSigner 的 Python 复刻）。

签名口径与 OpenApiSessionManager 验签一致：
- 参与签名的参数：AccessKeyId / SignatureMethod / SignatureNonce（仅三项）
- StringToSign = percentEncode(按 key 排序的 "k=v&k=v" 串)
- 签名 = Base64(HmacSHA1(StringToSign, SK, utf-8))
- percentEncode = URL 编码 + "%20"（空格）+ "%2A"（星号）+ "~" 还原（Java URLEncoder 语义）

传输方式：query 参数或 header（AccessKeyId/Signature/SignatureMethod/SignatureNonce），
这里用 header（避免 URL 落日志带签名）。
"""

import base64
import hashlib
import hmac
import urllib.parse

# OpenApiSigner.ENCODING / ALGORITHM_NAME。
_ENCODING = 'utf-8'
_ALGORITHM = 'sha1'  # HmacSHA1

SIGNATURE_METHOD = 'HMAC-SHA1'


def percent_encode(value: str) -> str:
    """Java URLEncoder.encode 的 RFC 修正版（同 OpenApiSigner.percentEncode）。"""
    encoded = urllib.parse.quote(value, safe='')
    return encoded.replace('+', '%20').replace('*', '%2A').replace('%7E', '~')


def compose_string_to_sign(queries: dict) -> str:
    """按 key 字典序拼 k=v&k=v，整体再 percentEncode 一次（同 OpenApiSigner）。"""
    pairs = '&'.join(
        f'{percent_encode(key)}={percent_encode(queries[key])}'
        for key in sorted(queries)
    )
    return percent_encode(pairs)


def sign(queries: dict, secret_key: str) -> str:
    """生成签名：Base64(HmacSHA1(composeStringToSign(queries), sk))。"""
    string_to_sign = compose_string_to_sign(queries)
    digest = hmac.new(secret_key.encode(_ENCODING), string_to_sign.encode(_ENCODING), _ALGORITHM).digest()
    return base64.b64encode(digest).decode(_ENCODING)


def build_headers(access_key: str, secret_key: str) -> dict:
    """构造一次调用所需的签名 header 集（nonce 每次随机）。"""
    import uuid

    queries = {
        'AccessKeyId': access_key,
        'SignatureMethod': SIGNATURE_METHOD,
        'SignatureNonce': uuid.uuid4().hex,
    }
    return {
        'AccessKeyId': access_key,
        'SignatureMethod': SIGNATURE_METHOD,
        'SignatureNonce': queries['SignatureNonce'],
        'Signature': sign(queries, secret_key),
    }
