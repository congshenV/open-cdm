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
package com.clougence.rdp.feishu;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.lang.reflect.Field;

import org.junit.Before;
import org.junit.Test;
import org.mockito.ArgumentCaptor;
import org.slf4j.Logger;

import com.clougence.clouddm.sdk.model.exception.ThirdPartyApiException;
import com.clougence.clouddm.team.provider.feishu.client.FeishuApi;
import com.clougence.clouddm.team.provider.feishu.client.FeishuClient;
import com.clougence.clouddm.team.provider.feishu.constants.FeishuI18nKeys;
import com.lark.oapi.Client;
import com.lark.oapi.service.contact.ContactService;
import com.lark.oapi.service.contact.v3.model.BatchGetIdUserReq;
import com.lark.oapi.service.contact.v3.model.BatchGetIdUserReqBody;
import com.lark.oapi.service.contact.v3.model.BatchGetIdUserResp;
import com.lark.oapi.service.contact.v3.model.BatchGetIdUserRespBody;
import com.lark.oapi.service.contact.v3.model.UserContactInfo;
import com.lark.oapi.service.contact.v3.resource.User;

public class FeishuUserLookupTest {

    private static final String PHONE   = "13800001111";
    private static final String EMAIL   = "zhangsan@example.com";
    private static final String USER_ID = "u_feishu_123";

    private FeishuApi feishuApi;
    private User      userResource;

    @Before
    public void setUp() throws Exception {
        Logger logger = mock(Logger.class);
        FeishuClient feishuClient = new FeishuClient(logger, "appId", "appSecret", 5, null);

        Client apiClient = mock(Client.class);
        ContactService contactService = mock(ContactService.class);
        userResource = mock(User.class);
        when(apiClient.contact()).thenReturn(contactService);
        when(contactService.user()).thenReturn(userResource);

        Field apiClientField = FeishuClient.class.getDeclaredField("apiClient");
        apiClientField.setAccessible(true);
        apiClientField.set(feishuClient, apiClient);

        feishuApi = feishuClient.getBindApi();
    }

    private static BatchGetIdUserResp respOf(String userId, String mobile, String email) {
        UserContactInfo info = new UserContactInfo();
        info.setUserId(userId);
        info.setMobile(mobile);
        info.setEmail(email);

        BatchGetIdUserRespBody body = new BatchGetIdUserRespBody();
        body.setUserList(new UserContactInfo[] { info });

        BatchGetIdUserResp resp = new BatchGetIdUserResp();
        resp.setData(body);
        return resp;
    }

    @Test
    public void getUserIdByPhoneShouldQueryWithMobiles() throws Exception {
        when(userResource.batchGetId(any(BatchGetIdUserReq.class))).thenReturn(respOf(USER_ID, PHONE, null));

        assertEquals(USER_ID, feishuApi.getUserIdByPhone(PHONE));

        ArgumentCaptor<BatchGetIdUserReq> captor = ArgumentCaptor.forClass(BatchGetIdUserReq.class);
        verify(userResource).batchGetId(captor.capture());
        BatchGetIdUserReqBody sent = captor.getValue().getBatchGetIdUserReqBody();
        assertEquals(1, sent.getMobiles().length);
        assertEquals(PHONE, sent.getMobiles()[0]);
        assertEquals(null, sent.getEmails());
    }

    @Test
    public void getUserIdByEmailShouldQueryWithEmails() throws Exception {
        when(userResource.batchGetId(any(BatchGetIdUserReq.class))).thenReturn(respOf(USER_ID, null, EMAIL));

        assertEquals(USER_ID, feishuApi.getUserIdByEmail(EMAIL));

        ArgumentCaptor<BatchGetIdUserReq> captor = ArgumentCaptor.forClass(BatchGetIdUserReq.class);
        verify(userResource).batchGetId(captor.capture());
        BatchGetIdUserReqBody sent = captor.getValue().getBatchGetIdUserReqBody();
        assertEquals(1, sent.getEmails().length);
        assertEquals(EMAIL, sent.getEmails()[0]);
        assertEquals(null, sent.getMobiles());
    }

    @Test
    public void getUserIdByEmailShouldFailWhenUserIdMissing() throws Exception {
        when(userResource.batchGetId(any(BatchGetIdUserReq.class))).thenReturn(respOf(null, null, EMAIL));

        try {
            feishuApi.getUserIdByEmail(EMAIL);
            fail("expected ThirdPartyApiException");
        } catch (ThirdPartyApiException e) {
            assertEquals(FeishuI18nKeys.FEISHU_NOT_FIND_USER_BY_EMAIL, e.getMessageKey());
        }
    }

    @Test
    public void phoneOrEmailShouldPreferPhoneWhenPresent() throws Exception {
        when(userResource.batchGetId(any(BatchGetIdUserReq.class))).thenReturn(respOf(USER_ID, PHONE, EMAIL));

        assertEquals(USER_ID, feishuApi.getUserIdByPhoneOrEmail(PHONE, EMAIL));

        ArgumentCaptor<BatchGetIdUserReq> captor = ArgumentCaptor.forClass(BatchGetIdUserReq.class);
        verify(userResource).batchGetId(captor.capture());
        assertEquals(PHONE, captor.getValue().getBatchGetIdUserReqBody().getMobiles()[0]);
    }

    @Test
    public void phoneOrEmailShouldFallBackToEmailWhenPhoneBlank() throws Exception {
        when(userResource.batchGetId(any(BatchGetIdUserReq.class))).thenReturn(respOf(USER_ID, null, EMAIL));

        assertEquals(USER_ID, feishuApi.getUserIdByPhoneOrEmail(" ", EMAIL));

        ArgumentCaptor<BatchGetIdUserReq> captor = ArgumentCaptor.forClass(BatchGetIdUserReq.class);
        verify(userResource).batchGetId(captor.capture());
        assertEquals(EMAIL, captor.getValue().getBatchGetIdUserReqBody().getEmails()[0]);
    }

    @Test
    public void phoneOrEmailShouldUseEmailWhenPhoneNull() throws Exception {
        when(userResource.batchGetId(any(BatchGetIdUserReq.class))).thenReturn(respOf(USER_ID, null, EMAIL));

        assertEquals(USER_ID, feishuApi.getUserIdByPhoneOrEmail(null, EMAIL));

        ArgumentCaptor<BatchGetIdUserReq> captor = ArgumentCaptor.forClass(BatchGetIdUserReq.class);
        verify(userResource).batchGetId(captor.capture());
        assertEquals(EMAIL, captor.getValue().getBatchGetIdUserReqBody().getEmails()[0]);
    }

    @Test
    public void phoneOrEmailShouldFailWhenBothBlank() throws Exception {
        try {
            feishuApi.getUserIdByPhoneOrEmail(null, "");
            fail("expected ThirdPartyApiException");
        } catch (ThirdPartyApiException e) {
            assertEquals(FeishuI18nKeys.FEISHU_NOT_FIND_USER_BY_PHONE_OR_EMAIL, e.getMessageKey());
        }
        verify(userResource, never()).batchGetId(any());
    }
}
