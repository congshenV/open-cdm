/**
 * dmops 备份相关展示映射。
 *
 * 后端透传阿里云原始枚举（FullBackup / Physical / Enable ...），
 * 这里统一转成 i18n key，未识别的值原样展示。
 */

const WEEKDAY_KEYS = {
  Monday: 'xing-qi-yi',
  Tuesday: 'xing-qi-er',
  Wednesday: 'xing-qi-san',
  Thursday: 'xing-qi-si',
  Friday: 'xing-qi-wu',
  Saturday: 'xing-qi-liu',
  Sunday: 'xing-qi-ri'
};

const BACKUP_TYPE_KEYS = {
  FullBackup: 'quan-liang-bei-fen',
  IncrementalBackup: 'zeng-liang-bei-fen'
};

const BACKUP_METHOD_KEYS = {
  Logical: 'luo-ji-bei-fen',
  Physical: 'wu-li-bei-fen',
  Snapshot: 'kuai-zhao-bei-fen'
};

const BACKUP_MODE_KEYS = {
  Automated: 'xi-tong-zi-dong',
  Manual: 'yong-hu-shou-dong'
};

const BACKUP_STATUS_KEYS = {
  Success: 'yi-wan-cheng',
  Failed: 'yi-shi-bai'
};

const BINLOG_STATUS_KEYS = {
  Uploading: 'ji-shang-chuan-zhong',
  Completed: 'shang-chuan-wan-cheng'
};

const COMPRESS_TYPE_KEYS = {
  0: 'bu-ya-suo',
  1: 'zlib-ya-suo',
  2: 'bing-xing-zlib-ya-suo',
  4: 'kuaisu-ya-suo',
  8: 'kuaisu-ya-suo'
};

const RELEASED_KEEP_KEYS = {
  None: 'bu-bao-liu',
  Lastest: 'bao-liu-zui-hou-yi-fen',
  All: 'quan-bu-bao-liu'
};

const ARCHIVE_KEEP_KEYS = {
  ByMonth: 'mei-yue-bao-liu',
  ByWeek: 'mei-zhou-bao-liu'
};

// 跨地域备份：BackupType/BackupMethod 是单字母缩写
const CROSS_BACKUP_TYPE_KEYS = {
  F: 'quan-liang-bei-fen',
  I: 'zeng-liang-bei-fen'
};

const CROSS_BACKUP_METHOD_KEYS = {
  L: 'luo-ji-bei-fen',
  P: 'wu-li-bei-fen'
};

const normalizeEnum = (value) =>
  String(value)
    .replace(/[_\-\s]/g, '')
    .toLowerCase();

// 阿里云不同接口的枚举值大小写/分隔符不完全一致，匹配时忽略这些差异。
const labelOf = (keys, value) => {
  if (value === null || value === undefined || value === '') {
    return '';
  }
  const matched = Object.keys(keys).find((key) => normalizeEnum(key) === normalizeEnum(value));
  return matched ? keys[matched] : '';
};

export const backupLabels = {
  methods: {
    weekdayLabel(value) {
      const key = labelOf(WEEKDAY_KEYS, value);
      return key ? this.$t(key) : value || '';
    },
    backupTypeLabel(value) {
      const key = labelOf(BACKUP_TYPE_KEYS, value);
      return key ? this.$t(key) : value || '-';
    },
    backupMethodLabel(value) {
      const key = labelOf(BACKUP_METHOD_KEYS, value);
      return key ? this.$t(key) : value || '-';
    },
    backupModeLabel(value) {
      const key = labelOf(BACKUP_MODE_KEYS, value);
      return key ? this.$t(key) : value || '-';
    },
    backupStatusLabel(value) {
      const key = labelOf(BACKUP_STATUS_KEYS, value);
      return key ? this.$t(key) : value || '-';
    },
    backupStatusColor(value) {
      return value === 'Success' ? 'green' : value === 'Failed' ? 'red' : 'default';
    },
    binlogStatusLabel(value) {
      const key = labelOf(BINLOG_STATUS_KEYS, value);
      return key ? this.$t(key) : value || '-';
    },
    compressTypeLabel(value) {
      const key = labelOf(COMPRESS_TYPE_KEYS, value);
      return key ? this.$t(key) : value || '-';
    },
    releasedKeepLabel(value) {
      const key = labelOf(RELEASED_KEEP_KEYS, value);
      return key ? this.$t(key) : value || '-';
    },
    archiveKeepLabel(value) {
      const key = labelOf(ARCHIVE_KEEP_KEYS, value);
      return key ? this.$t(key) : value;
    },
    crossBackupTypeLabel(value) {
      const key = labelOf(CROSS_BACKUP_TYPE_KEYS, value);
      return key ? this.$t(key) : value || '-';
    },
    crossBackupMethodLabel(value) {
      const key = labelOf(CROSS_BACKUP_METHOD_KEYS, value);
      return key ? this.$t(key) : value || '-';
    }
  }
};

export default backupLabels;
