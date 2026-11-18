package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.Map;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

class HealthControllerTest {

  @Test
  void health_shouldReportDegradedWhenConnectionFails() throws Exception {
    DataSource ds = mock(DataSource.class);
    when(ds.getConnection()).thenThrow(new SQLException("down"));

    ResponseEntity<Map<String, Object>> res = new HealthController(ds).health();

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
    assertThat(res.getBody()).containsEntry("status", "degraded");
    assertThat(res.getBody().get("database")).isEqualTo(Map.of("status", "down"));
  }

  @Test
  void health_shouldReportDegradedWhenConnectionInvalid() throws Exception {
    DataSource ds = mock(DataSource.class);
    Connection conn = mock(Connection.class);
    when(ds.getConnection()).thenReturn(conn);
    when(conn.isValid(3)).thenReturn(false);

    ResponseEntity<Map<String, Object>> res = new HealthController(ds).health();

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
    verify(conn).close();
  }
}
