/**
 * 备份恢复演练状态映射（数据库状态机：pending/cloning/success/failed/canceled；
 * comparing/partial 二期引入）。
 *
 * display_status 是服务端派生的展示状态（不改数据库枚举）：
 * success 之后按阶段推进——awaiting_verify（待数据校验）→ verified（数据校验完成）
 * → done（演练完成，人工下线确认后）；pending/cloning/failed/canceled 原样透传。
 */

// 状态徽标 a-tag 的 color。
const STATUS_COLORS = {
  pending: 'default',
  cloning: 'processing',
  success: 'green',
  failed: 'red',
  canceled: 'default',
  comparing: 'processing',
  partial: 'orange',
  // 派生展示状态
  awaiting_verify: 'gold',
  verified: 'cyan',
  done: 'green'
};

// pinyin i18n key。
const STATUS_KEYS = {
  pending: 'dai-ti-jiao',
  cloning: 'ke-long-zhong',
  comparing: 'dui-bi-zhong',
  success: 'ke-long-wan-cheng',
  partial: 'bu-fen-tong-guo',
  failed: 'shi-bai',
  canceled: 'yi-qu-xiao',
  // 派生展示状态
  awaiting_verify: 'dai-shu-ju-jiao-yan',
  verified: 'shu-ju-jiao-yan-wan-cheng',
  done: 'yan-lian-wan-cheng'
};

function labelOf(t, value, keys) {
  if (value === null || value === undefined || value === '') {
    return '';
  }
  const key = keys[String(value)];
  return key ? t(key) : String(value);
}

export const drillLabels = {
  methods: {
    drillStatusLabel(value) {
      return labelOf(this.$t, value, STATUS_KEYS);
    },
    drillStatusColor(value) {
      return STATUS_COLORS[String(value)] || 'default';
    }
  }
};

// 未终态判断（驱动 10s 轮询与取消按钮可用性）。
export const DRILL_ACTIVE_STATUSES = ['pending', 'cloning', 'comparing'];

export function isDrillActive(status) {
  return DRILL_ACTIVE_STATUSES.includes(String(status));
}
