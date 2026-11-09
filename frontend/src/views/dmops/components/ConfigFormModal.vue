<template>
  <a-modal
    :open="open"
    :title="isEdit ? $t('bian-ji-pei-zhi-xiang') : $t('xin-jian-pei-zhi-xiang')"
    :width="560"
    :mask-closable="false"
    :confirm-loading="saving"
    :ok-text="$t('bao-cun')"
    :cancel-text="$t('qu-xiao')"
    @ok="submit"
    @cancel="close"
  >
    <a-form class="dmops-form" layout="vertical">
      <a-form-item :label="$t('mo-kuai')" required>
        <a-select v-model:value="form.config_scope" :placeholder="$t('qing-xuan-ze-mo-kuai')">
          <a-select-option v-for="scope in scopes" :key="scope" :value="scope">{{ scope }}</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item :label="$t('pei-zhi-ming')" required>
        <a-input v-model:value="form.config_name" :maxlength="255" :placeholder="$t('qing-shu-ru-pei-zhi-ming')" />
      </a-form-item>
      <a-form-item :label="$t('shu-ju-lei-xing')" required>
        <a-select v-model:value="form.config_type" :placeholder="$t('qing-xuan-ze-shu-ju-lei-xing')">
          <a-select-option v-for="type in types" :key="type" :value="type">{{ type }}</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item :label="$t('pei-zhi-jian')" required>
        <a-input v-model:value="form.config_key" :maxlength="255" :disabled="isEdit" :placeholder="$t('qing-shu-ru-pei-zhi-jian')" />
      </a-form-item>
      <a-form-item required>
        <template #label>
          {{ $t('pei-zhi-zhi') }}
          <span v-if="isListType" class="dmops-form__hint">{{ $t('qing-tian-xie-json-shu-zu') }}</span>
        </template>
        <a-textarea v-model:value="form.config_value" :rows="5" :placeholder="valuePlaceholder" />
      </a-form-item>
      <a-form-item :label="$t('shi-fou-jia-mi')">
        <a-switch v-model:checked="form.is_encrypt" />
      </a-form-item>
      <a-form-item :label="$t('miao-shu')">
        <a-textarea v-model:value="form.description" :rows="2" :maxlength="512" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script>
import Toast from '@/utils/toast';
import { createConfig, getConfig, updateConfig } from '@/services/http/dmops';

// 与后端 config_service 的 CONFIG_SCOPES / CONFIG_TYPES 保持一致
const SCOPES = ['base', 'rds', 'redis'];
const TYPES = ['str', 'int', 'float', 'bool', 'str_list', 'int_list', 'json', 'json_list'];

const EMPTY_FORM = () => ({
  config_scope: undefined,
  config_name: '',
  config_type: undefined,
  config_key: '',
  config_value: '',
  is_encrypt: false,
  description: ''
});

export default {
  name: 'DmOpsConfigFormModal',
  props: {
    open: {
      type: Boolean,
      default: false
    },
    config: {
      type: Object,
      default: null
    }
  },
  emits: ['update:open', 'saved'],
  data() {
    return {
      scopes: SCOPES,
      types: TYPES,
      saving: false,
      form: EMPTY_FORM()
    };
  },
  computed: {
    isEdit() {
      return !!(this.config && this.config.id);
    },
    isListType() {
      return ['str_list', 'int_list', 'json_list'].includes(this.form.config_type);
    },
    valuePlaceholder() {
      if (this.isListType) {
        return '["a", "b"]';
      }
      if (this.form.config_type === 'json') {
        return '{"key": "value"}';
      }
      return this.$t('qing-shu-ru-pei-zhi-zhi');
    }
  },
  watch: {
    open(value) {
      if (value) {
        this.reset();
      }
    },
    config() {
      if (this.open) {
        this.reset();
      }
    }
  },
  methods: {
    // 编辑时列表接口返回的是脱敏值，这里先取详情拿明文回填
    async reset() {
      if (!this.isEdit) {
        this.form = EMPTY_FORM();
        return;
      }

      try {
        const detail = await getConfig(this.config.id);
        this.form = {
          config_scope: detail.config_scope,
          config_name: detail.config_name || '',
          config_type: detail.config_type,
          config_key: detail.config_key || '',
          config_value: detail.config_value || '',
          is_encrypt: !!detail.is_encrypt,
          description: detail.description || ''
        };
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
        this.close();
      }
    },
    close() {
      this.$emit('update:open', false);
    },
    validate() {
      if (!this.form.config_scope) {
        Toast.error(this.$t('qing-xuan-ze-mo-kuai'));
        return false;
      }
      if (!(this.form.config_name || '').trim()) {
        Toast.error(this.$t('pei-zhi-ming-bu-neng-wei-kong'));
        return false;
      }
      if (!this.form.config_type) {
        Toast.error(this.$t('qing-xuan-ze-shu-ju-lei-xing'));
        return false;
      }
      if (!(this.form.config_key || '').trim()) {
        Toast.error(this.$t('pei-zhi-jian-bu-neng-wei-kong'));
        return false;
      }
      if (!(this.form.config_value || '').trim()) {
        Toast.error(this.$t('pei-zhi-zhi-bu-neng-wei-kong'));
        return false;
      }
      return true;
    },
    async submit() {
      if (!this.validate()) {
        return;
      }

      const payload = {
        config_scope: this.form.config_scope,
        config_name: this.form.config_name.trim(),
        config_type: this.form.config_type,
        config_key: this.form.config_key.trim(),
        config_value: this.form.config_value.trim(),
        is_encrypt: this.form.is_encrypt,
        description: (this.form.description || '').trim()
      };

      this.saving = true;
      try {
        if (this.isEdit) {
          await updateConfig(this.config.id, payload);
        } else {
          await createConfig(payload);
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

.dmops-form__hint {
  margin-left: 4px;
  font-size: 12px;
  font-weight: normal;
  color: var(--text-tertiary);
}
</style>
