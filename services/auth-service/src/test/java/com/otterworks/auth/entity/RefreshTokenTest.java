package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class RefreshTokenTest {

  @Test
  void aFreshTokenIsNotRevokedAndHasNoTimestamps() {
    RefreshToken token = new RefreshToken();

    assertThat(token.isRevoked()).isFalse();
    assertThat(token.getId()).isNull();
    assertThat(token.getUser()).isNull();
    assertThat(token.getTokenId()).isNull();
    assertThat(token.getExpiresAt()).isNull();
    assertThat(token.getCreatedAt()).isNull();
  }

  @Test
  void settersRoundTrip() {
    UUID id = UUID.randomUUID();
    Instant expiresAt = Instant.parse("2024-12-31T23:59:59Z");
    User user = new User();
    user.setId(UUID.randomUUID());

    RefreshToken token = new RefreshToken();
    token.setId(id);
    token.setUser(user);
    token.setTokenId("jti-123");
    token.setExpiresAt(expiresAt);
    token.setRevoked(true);

    assertThat(token.getId()).isEqualTo(id);
    assertThat(token.getUser()).isSameAs(user);
    assertThat(token.getTokenId()).isEqualTo("jti-123");
    assertThat(token.getExpiresAt()).isEqualTo(expiresAt);
    assertThat(token.isRevoked()).isTrue();
  }

  @Test
  void onCreateStampsCreatedAt() {
    RefreshToken token = new RefreshToken();
    Instant before = Instant.now();

    token.onCreate();

    assertThat(token.getCreatedAt()).isNotNull().isAfterOrEqualTo(before);
  }
}
