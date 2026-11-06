"""应用级配置。

独立服务，配置只从环境变量读取，不依赖任何配置中心。
所有配置项都可以用同名大写环境变量覆盖。
"""

import os
import socket


def _env_str(name: str, default: str = '') -> str:
    return os.getenv(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


Hostname = socket.gethostname().split('.')[0]
ProjectName = 'dmops'


class Server:
    """Web 服务配置。"""

    host: str = _env_str('DMOPS_HOST', '0.0.0.0')
    port: int = _env_int('DMOPS_PORT', 8080)
    debug: bool = _env_bool('DMOPS_DEBUG', False)


class Identity:
    """console 转发请求时的身份签名校验。"""

    # 与 CloudDM console 的 dmops.proxy.identity.secret 必须一致。
    secret: str = _env_str('DMOPS_IDENTITY_SECRET', '')
    # 仅本地直连调试时设为 false，绕过签名校验。
    verify_enabled: bool = _env_bool('DMOPS_IDENTITY_VERIFY_ENABLED', True)

    # console 注入的 header 名。
    user_header: str = 'X-DmOps-User'
    signature_header: str = 'X-DmOps-Signature'
    request_id_header: str = 'X-Request-Id'


class Log:
    """日志配置。"""

    level: str = _env_str('DMOPS_LOG_LEVEL', 'INFO')
    format: str = '%(asctime)s.%(msecs)03d [%(levelname)s] %(process)d %(filename)s:%(lineno)d %(message)s'
    date_fmt: str = '%Y-%m-%d %H:%M:%S'


class Database:
    """数据库配置。复用 CloudDM 的 MySQL，本地默认指向 cdmgr 库。"""

    host: str = _env_str('DMOPS_DB_HOST', '127.0.0.1')
    port: int = _env_int('DMOPS_DB_PORT', 13307)
    name: str = _env_str('DMOPS_DB_NAME', 'cdmgr')
    user: str = _env_str('DMOPS_DB_USER', 'root')
    password: str = _env_str('DMOPS_DB_PASSWORD', '')
    charset: str = _env_str('DMOPS_DB_CHARSET', 'utf8mb4')
    pool_size: int = _env_int('DMOPS_DB_POOL_SIZE', 5)
    max_overflow: int = _env_int('DMOPS_DB_MAX_OVERFLOW', 10)


class Config:
    """配置管理。

    encrypt_secret 为 AES 加密密钥（32 字节），只用于 is_encrypt=true 的配置项加密，
    生成方式：openssl rand -hex 16。与身份 secret 互相独立，不要复用同一个值。
    """

    encrypt_secret: str = _env_str('DMOPS_CONFIG_ENCRYPT_SECRET', '')


class Aliyun:
    """阿里云 OpenAPI 调用配置。"""

    read_timeout_ms: int = _env_int('DMOPS_ALIYUN_READ_TIMEOUT_MS', 30000)
    connect_timeout_ms: int = _env_int('DMOPS_ALIYUN_CONNECT_TIMEOUT_MS', 10000)
    sync_workers: int = _env_int('DMOPS_ALIYUN_SYNC_WORKERS', 4)
    max_instances_per_region: int = _env_int('DMOPS_ALIYUN_MAX_INSTANCES_PER_REGION', 5000)
    instance_name_max_len: int = _env_int('DMOPS_ALIYUN_INSTANCE_NAME_MAX_LEN', 256)


class Drill:
    """备份恢复演练（一期克隆链路）配置。见 docs/backup-drill-design.md §8。"""

    # 全局并发演练数：同一时刻允许处于 pending/cloning 的演练条数。
    max_concurrency: int = _env_int('DMOPS_DRILL_MAX_CONCURRENCY', 1)
    # 克隆阶段超时（分钟），超时判 failed；克隆实例可能仍会被阿里云创建，进待下线清单。
    clone_timeout_min: int = _env_int('DMOPS_DRILL_CLONE_TIMEOUT_MIN', 120)
    # worker 扫描间隔（秒）。
    scan_interval_sec: int = _env_int('DMOPS_DRILL_SCAN_INTERVAL_SEC', 10)
    # 克隆轮询间隔（秒）+ 心跳落库节流（秒）；心跳窗口超时可被重新抢占。
    poll_interval_sec: int = _env_int('DMOPS_DRILL_POLL_INTERVAL_SEC', 30)
    heartbeat_sec: int = _env_int('DMOPS_DRILL_HEARTBEAT_SEC', 60)
    heartbeat_timeout_sec: int = _env_int('DMOPS_DRILL_HEARTBEAT_TIMEOUT_SEC', 600)
    # 克隆轮询宽容：实例不存在等硬错误连续出现该次数才判 failed（异步创建窗口）。
    poll_hard_error_limit: int = _env_int('DMOPS_DRILL_POLL_HARD_ERROR_LIMIT', 10)
    # 表数据校验：单次最多选定表数（§4.2）。
    max_tables: int = _env_int('DMOPS_DRILL_MAX_TABLES', 5)
    # 稳定行游标扫描：批大小与最大批数。
    scan_batch_rows: int = _env_int('DMOPS_DRILL_SCAN_BATCH_ROWS', 100)
    scan_max_batches: int = _env_int('DMOPS_DRILL_SCAN_MAX_BATCHES', 50)
    # 行级校验：每表最大尝试次数与重试间隔（秒）。
    row_attempts: int = _env_int('DMOPS_DRILL_ROW_ATTEMPTS', 10)
    row_retry_interval_sec: int = _env_int('DMOPS_DRILL_ROW_RETRY_INTERVAL_SEC', 30)


class Cdm:
    """CloudDM console 出向调用配置（注册数据源，JWT 透传）。"""

    # 本机调试默认指向 console 单机模式；生产为同集群 console 地址。
    console_url: str = _env_str('DMOPS_CDM_CONSOLE_URL', 'http://127.0.0.1:8222')
    # addDs 的 envId 默认值；clusterId 仅在集群列表为空时兜底（正常预填取清单第一项）。
    env_id: int = _env_int('DMOPS_CDM_ENV_ID', 1)
    cluster_id: int = _env_int('DMOPS_CDM_CLUSTER_ID', 2)

