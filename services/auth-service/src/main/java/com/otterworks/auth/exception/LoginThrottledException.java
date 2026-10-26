package com.otterworks.auth.exception;

/** Thrown when an account has too many recent failed logins and is temporarily locked. */
public class LoginThrottledException extends RuntimeException {

  private final long retryAfterSeconds;

  public LoginThrottledException(long retryAfterSeconds) {
    super("Too many failed login attempts. Try again later.");
    this.retryAfterSeconds = retryAfterSeconds;
  }

  public long getRetryAfterSeconds() {
    return retryAfterSeconds;
  }
}
