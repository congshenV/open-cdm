<template>
  <!-- 配置管理：内容待接入 dmops 接口，先给空态占位 -->
  <div class="content-wrapper dmops-page">
    <div class="dmops-page__empty">
      <CustomIcon type="icon-v2-Empty" size="48px" />
      <p class="dmops-page__empty-text">{{ $t('zan-wu-shu-ju') }}</p>
    </div>
  </div>
</template>

<script>
export default {
  name: 'DmOpsConfigManage'
};
</script>

<style lang="less" scoped>
// content-wrapper 已提供 padding: 16px（与控制台列表页一致），这里只补纵向布局
.dmops-page {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;

  &__empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    // 图标跟随这个颜色（CustomIcon 默认 currentColor）
    color: var(--text-tertiary);
  }

  &__empty-text {
    margin: 0;
    font-size: 13px;
    line-height: 20px;
    color: var(--text-secondary);
  }
}
</style>
