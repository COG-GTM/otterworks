package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.Map;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

@ExtendWith(MockitoExtension.class)
class HealthControllerTest {

  @Mock private DataSource dataSource;
  @Mock private Connection connection;

  @Test
  void health_shouldReportHealthyWhenConnectionIsValid() throws SQLException {
    when(dataSource.getConnection()).thenReturn(connection);
    when(connection.isValid(3)).thenReturn(true);

    ResponseEntity<Map<String, Object>> response = new HealthController(dataSource).health();

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody())
        .containsEntry("service", "auth-service")
        .containsEntry("status", "healthy")
        .containsEntry("database", Map.of("status", "up"));
  }

  @Test
  void health_shouldReportDegradedWhenConnectionIsInvalid() throws SQLException {
    when(dataSource.getConnection()).thenReturn(connection);
    when(connection.isValid(3)).thenReturn(false);

    ResponseEntity<Map<String, Object>> response = new HealthController(dataSource).health();

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
    assertThat(response.getBody())
        .containsEntry("status", "degraded")
        .containsEntry("database", Map.of("status", "down"));
  }

  @Test
  void health_shouldReportDegradedWhenConnectionCannotBeOpened() throws SQLException {
    when(dataSource.getConnection()).thenThrow(new SQLException("connection refused"));

    ResponseEntity<Map<String, Object>> response = new HealthController(dataSource).health();

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
    assertThat(response.getBody()).containsEntry("status", "degraded");
  }
}
