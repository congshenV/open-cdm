/**
 * dmops 实例列表的展示映射。
 *
 * 后端返回的是阿里云原始枚举值（Running / Basic / Primary ...），这里统一转成 i18n key，
 * 未识别的值原样展示，避免新增枚举时页面出现空白。
 */

const STATUS_KEYS = {
  Running: 'yun-xing-zhong',
  Creating: 'zheng-zai-chuang-jian',
  Deleting: 'shan-chu-zhong',
  Rebooting: 'chong-qi-zhong',
  Migrating: 'qian-yi-zhong',
  Upgrading: 'sheng-ji-zhong',
  DBInstanceClassChanging: 'bian-pei-zhong',
  EngineVersionUpgrading: 'sheng-ji-zhong',
  BackupRecovering: 'hui-fu-zhong',
  Restoring: 'hui-fu-zhong',
  Maintaining: 'wei-hu-zhong',
  Locked: 'yi-suo-ding',
  Released: 'yi-shi-fang'
};

const STATUS_COLORS = {
  Running: 'green',
  Creating: 'blue',
  Rebooting: 'blue',
  Migrating: 'blue',
  Upgrading: 'blue',
  DBInstanceClassChanging: 'blue',
  EngineVersionUpgrading: 'blue',
  BackupRecovering: 'blue',
  Restoring: 'blue',
  Maintaining: 'orange',
  Locked: 'red',
  Released: 'default'
};

const INSTANCE_TYPE_KEYS = {
  Primary: 'zhu-shi-li',
  Readonly: 'du-shi-li',
  Guard: 'zai-bei-shi-li',
  Temp: 'lin-shi-shi-li'
};

const CATEGORY_KEYS = {
  Basic: 'ji-chu-ban',
  HighAvailability: 'gao-ke-yong-ban',
  Cluster: 'ji-qun-ban',
  Serverless: 'serverless-ban',
  ServerlessBasic: 'serverless-ji-chu-ban',
  ServerlessStandard: 'serverless-biao-zhun-ban'
};

const PAY_TYPE_KEYS = {
  Prepaid: 'bao-nian-bao-yue',
  Postpaid: 'an-liang-fu-fei'
};

const NETWORK_TYPE_KEYS = {
  VPC: 'zhuan-you-wang-luo',
  Classic: 'jing-dian-wang-luo'
};

const normalizeEnum = (value) =>
  String(value)
    .replace(/[_\-\s]/g, '')
    .toLowerCase();

// 阿里云不同接口的枚举值大小写/分隔符不完全一致，匹配时忽略这些差异。
const labelOf = (t, keys, value) => {
  if (!value) {
    return '';
  }
  if (keys[value]) {
    return t(keys[value]);
  }
  const target = normalizeEnum(value);
  const matched = Object.keys(keys).find((key) => normalizeEnum(key) === target);
  return matched ? t(keys[matched]) : value;
};

/** 按 1024 进制自适应单位：>1024MB 用 GB，>1024GB 用 TB。 */
export function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) {
    return '';
  }
  if (value === 0) {
    return '0 B';
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${Math.round(size * 10) / 10} ${units[index]}`;
}

export const statusLabel = (t, value) => labelOf(t, STATUS_KEYS, value);

export const statusColor = (value) => STATUS_COLORS[value] || 'default';

export const instanceTypeLabel = (t, value) => labelOf(t, INSTANCE_TYPE_KEYS, value);

export const categoryLabel = (t, value) => labelOf(t, CATEGORY_KEYS, value);

export const payTypeLabel = (t, value) => labelOf(t, PAY_TYPE_KEYS, value);

export const networkTypeLabel = (t, value) => labelOf(t, NETWORK_TYPE_KEYS, value);
