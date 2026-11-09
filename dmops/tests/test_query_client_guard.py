"""query_client 空壳响应守卫单测（sidecar 会话池满时不得伪装成 0 行）。"""

import pytest

from app.adapter.clouddm import query_client
from app.util.errors import ApiError


def test_extract_raises_on_missing_result_meta():
    """columnList 为 None（查询未真正执行）必须报错，并携带 msgList 的真实错误。"""
    fake_result = {
        'rows': [],
        'columnList': None,
        'receiveMode': None,
        'msgList': [
            {
                'entities': [
                    {
                        'level': 'Error',
                        'message': 'exceed session max pool size: 5',
                    }
                ]
            }
        ],
    }
    with pytest.raises(ApiError) as exc:
        query_client._extract(fake_result)
    assert 'exceed session max pool size' in exc.value.user_message


def test_extract_raises_on_empty_shell_without_msg():
    """空壳且无 msgList：报通用错误（仍是失败，不是 0 行）。"""
    with pytest.raises(ApiError) as exc:
        query_client._extract({'rows': [], 'columnList': None})
    assert 'SQL 未执行成功' in exc.value.user_message


def test_extract_normal_rows():
    """正常响应：columnList + rows（ResultSetValue 兼容 dict 与标量两种形态）。"""
    fake_result = {
        'columnList': ['db_name', 'table_count'],
        'rows': [
            {'data': ['app_db', {'value': 152}]},
            {'data': [{'value': 'user_db'}, 37]},
        ],
    }
    columns, rows = query_client._extract(fake_result)
    assert columns == ['db_name', 'table_count']
    assert rows == [['app_db', 152], ['user_db', 37]]


def test_extract_zero_columns_ok():
    """无列名但有 meta（如 SELECT 无结果）不触发守卫——只有 columnList 为 None 才是空壳。"""
    columns, rows = query_client._extract({'columnList': [], 'rows': []})
    assert columns == []
    assert rows == []
