/*
 * Copyright 2026 杭州开云集致科技有限公司
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.clougence.clouddm.sdk.execute.dsconf;

import java.lang.reflect.Field;
import java.util.HashMap;
import java.util.Map;

import com.clougence.clouddm.base.metadata.ds.ConfigDef;
import com.clougence.clouddm.base.metadata.ds.DataSourceConfig;
import com.clougence.clouddm.sdk.execute.session.SessionContextDTO;
import com.clougence.utils.StringUtils;

import lombok.extern.slf4j.Slf4j;

/**
 * Apply session-level catalog/schema to the datasource config before a connection is created,
 * so ticket execution lands on the target database selected in the ticket instead of the
 * datasource default.
 */
@Slf4j
public class DsConfigOverrideUtils {

    public static void applySessionContext(DataSourceConfig dsConfig, SessionContextDTO contextDTO) {
        if (dsConfig == null || contextDTO == null) {
            return;
        }

        Map<String, String> overrides = new HashMap<>();
        if (StringUtils.isNotBlank(contextDTO.getRdbCatalog())) {
            overrides.put(DsConfigField.DEFAULT_DATABASE.getConfigName(), contextDTO.getRdbCatalog());
        }
        if (StringUtils.isNotBlank(contextDTO.getRdbSchema())) {
            overrides.put(DsConfigField.DEFAULT_SCHEMA.getConfigName(), contextDTO.getRdbSchema());
        }
        if (overrides.isEmpty()) {
            return;
        }

        applyConfigValues(dsConfig, dsConfig.getClass(), overrides);
    }

    private static void applyConfigValues(Object instance, Class<?> clazz, Map<String, String> overrides) {
        try {
            for (Field field : clazz.getDeclaredFields()) {
                ConfigDef configDef = field.getAnnotation(ConfigDef.class);
                if (configDef == null) {
                    continue;
                }

                String overrideValue = overrides.get(configDef.name());
                if (overrideValue == null) {
                    continue;
                }

                field.setAccessible(true);
                if (field.getType() == String.class) {
                    field.set(instance, overrideValue);
                }
            }

            if (clazz.getSuperclass() != null && clazz.getSuperclass() != Object.class) {
                applyConfigValues(instance, clazz.getSuperclass(), overrides);
            }
        } catch (IllegalAccessException e) {
            String msg = "apply session context to datasource config failed, msg:" + e.getMessage();
            log.error(msg, e);
            throw new RuntimeException(msg, e);
        }
    }
}
