package com.otterworks.auth.audit;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.Map;
import lombok.Builder;
import lombok.Value;

/** Audit event body for {@code POST /api/v1/audit/events} (audit contract v2). */
@Value
@Builder(toBuilder = true)
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AuditEvent {

  public static final String OUTCOME_SUCCESS = "success";
  public static final String OUTCOME_FAILURE = "failure";
  public static final String OUTCOME_DENIED = "denied";

  public static final String ANONYMOUS = "anonymous";

  String userId;
  String actorEmail;
  String actorType;
  String tenantId;
  String action;
  String resourceType;
  String resourceId;
  String outcome;
  Map<String, String> details;
  String ipAddress;
  String userAgent;
  String requestId;
  String serviceName;
  String timestamp;
}
