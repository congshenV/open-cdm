<template>
  <a-modal
    :open="open"
    :title="isEdit ? $t('bian-ji-zhang-hao') : $t('xin-jian-zhang-hao')"
    :width="560"
    :mask-closable="false"
    :confirm-loading="saving"
    :ok-text="$t('bao-cun')"
    :cancel-text="$t('qu-xiao')"
    @ok="submit"
    @cancel="close"
  >
    <a-form class="dmops-form" layout="vertical">
      <a-form-item :label="$t('a-li-yun-zhang-hao-id')" required>
        <a-input v-model:value="form.cloud_account_id" :disabled="isEdit" :maxlength="32" :placeholder="$t('qing-shu-ru-a-li-yun-zhang-hao-id')" />
      </a-form-item>
      <a-form-item :label="$t('ming-cheng')" required>
        <a-input v-model:value="form.name" :maxlength="128" :placeholder="$t('qing-shu-ru-ming-cheng')" />
      </a-form-item>
      <a-form-item :label="$t('miao-shu')">
        <a-textarea v-model:value="form.description" :rows="3" :maxlength="512" />
      </a-form-item>
      <a-form-item :label="$t('mo-ren-di-qu')">
        <a-input v-model:value="form.default_region" :maxlength="32" placeholder="cn-hangzhou" />
      </a-form-item>
      <a-form-item :label="$t('qi-yong')">
        <a-switch v-model:checked="form.enabled" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script>
import Toast from '@/utils/toast';
import { createAccount, updateAccount } from '@/services/http/dmops';

const ACCOUNT_ID_PATTERN = /^\d{6,32}$/;
// 账号 ID 位数与后端的 6-32 位校验保持一致
const EMPTY_FORM = () => ({
  cloud_account_id: '',
  name: '',
  description: '',
  default_region: 'cn-hangzhou',
  enabled: true
});

export default {
  name: 'DmOpsAccountFormModal',
  props: {
    open: {
      type: Boolean,
      default: false
    },
    account: {
      type: Object,
      default: null
    }
  },
  emits: ['update:open', 'saved'],
  data() {
    return {
      saving: false,
      form: EMPTY_FORM()
    };
  },
  computed: {
    isEdit() {
      return !!(this.account && this.account.id);
    }
  },
  watch: {
    open(value) {
      if (value) {
        this.reset();
      }
    },
    account() {
      if (this.open) {
        this.reset();
      }
    }
  },
  methods: {
    reset() {
      if (this.isEdit) {
        this.form = {
          cloud_account_id: this.account.cloud_account_id || '',
          name: this.account.name || '',
          description: this.account.description || '',
          default_region: this.account.default_region || 'cn-hangzhou',
          enabled: !!this.account.enabled
        };
        return;
      }
      this.form = EMPTY_FORM();
    },
    close() {
      this.$emit('update:open', false);
    },
    validate() {
      const cloudAccountId = (this.form.cloud_account_id || '').trim();
      if (!ACCOUNT_ID_PATTERN.test(cloudAccountId)) {
        Toast.error(this.$t('zhang-hao-id-ge-shi-bu-zheng-que'));
        return false;
      }
      if (!(this.form.name || '').trim()) {
        Toast.error(this.$t('zhang-hao-ming-cheng-bu-neng-wei-kong'));
        return false;
      }
      return true;
    },
    async submit() {
      if (!this.validate()) {
        return;
      }

      const payload = {
        cloud_account_id: this.form.cloud_account_id.trim(),
        name: this.form.name.trim(),
        description: (this.form.description || '').trim(),
        default_region: (this.form.default_region || '').trim() || 'cn-hangzhou',
        enabled: this.form.enabled
      };

      this.saving = true;
      try {
        if (this.isEdit) {
          // 账号 ID 不允许修改，只提交基础信息
          delete payload.cloud_account_id;
          await updateAccount(this.account.id, payload);
        } else {
          await createAccount(payload);
        }
        Toast.success(this.$t('cao-zuo-cheng-gong'));
        this.$emit('saved');
        this.close();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.saving = false;
      }
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-form {
  padding-top: 4px;
}
</style>
