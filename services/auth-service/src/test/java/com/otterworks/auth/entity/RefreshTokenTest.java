package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class RefreshTokenTest {

  @Test
  void newTokenIsNotRevokedAndHasNoCreationStampYet() {
    RefreshToken token = new RefreshToken();

    assertThat(token.isRevoked()).isFalse();
    assertThat(token.getCreatedAt()).isNull();
    assertThat(token.getId()).isNull();
  }

  @Test
  void onCreateStampsCreatedAt() {
    RefreshToken token = new RefreshToken();

    token.onCreate();

    assertThat(token.getCreatedAt()).isNotNull().isBeforeOrEqualTo(Instant.now());
  }

  @Test
  void mutatorsRoundTripEveryField() {
    UUID id = UUID.randomUUID();
    Instant expiresAt = Instant.parse("2030-01-01T00:00:00Z");
    User user = new User();
    user.setId(UUID.randomUUID());
    RefreshToken token = new RefreshToken();

    token.setId(id);
    token.setUser(user);
    token.setTokenId("jti-abc");
    token.setExpiresAt(expiresAt);
    token.setRevoked(true);
    token.setCreatedAt(expiresAt.minus(1, ChronoUnit.DAYS));

    assertThat(token.getId()).isEqualTo(id);
    assertThat(token.getUser()).isSameAs(user);
    assertThat(token.getTokenId()).isEqualTo("jti-abc");
    assertThat(token.getExpiresAt()).isEqualTo(expiresAt);
    assertThat(token.isRevoked()).isTrue();
    assertThat(token.getCreatedAt()).isEqualTo(expiresAt.minus(1, ChronoUnit.DAYS));
  }
}
