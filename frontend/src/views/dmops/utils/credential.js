/**
 * 认证方式在页面上的展示与可用范围。
 *
 * 后端支持 8 种，页面只维护常用三种；其余类型遇到时按原始值展示，并提示需要切换。
 */
export const CREDENTIAL_TYPES = ['access_key', 'sts', 'ram_role_arn'];

const CREDENTIAL_TYPE_KEYS = {
  access_key: 'access-key',
  sts: 'sts-lin-shi-ping-zheng',
  ram_role_arn: 'ram-jiao-se'
};

export function credentialTypeLabel(t, type) {
  const key = CREDENTIAL_TYPE_KEYS[type];
  return key ? t(key) : type || '';
}
