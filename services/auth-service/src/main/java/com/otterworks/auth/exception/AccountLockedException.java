package com.otterworks.auth.exception;

import java.time.Instant;
import lombok.Getter;

@Getter
public class AccountLockedException extends RuntimeException {

  private final Instant lockedUntil;

  public AccountLockedException(Instant lockedUntil) {
    super("Account temporarily locked due to too many failed login attempts");
    this.lockedUntil = lockedUntil;
  }
}
