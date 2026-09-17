package com.otterworks.auth.exception;

/** Thrown when an account is temporarily locked after repeated failed logins. */
public class AccountLockedException extends RuntimeException {

  private final long retryAfterSeconds;

  public AccountLockedException(long retryAfterSeconds) {
    super("Account temporarily locked due to repeated failed login attempts");
    this.retryAfterSeconds = retryAfterSeconds;
  }

  public long getRetryAfterSeconds() {
    return retryAfterSeconds;
  }
}
