package com.otterworks.auth.exception;

/** Thrown when one credential is tried more often than the throttle allows. */
public class TooManyLoginAttemptsException extends RuntimeException {

  private final long retryAfterSeconds;

  public TooManyLoginAttemptsException(long retryAfterSeconds) {
    super("Too many login attempts for these credentials");
    this.retryAfterSeconds = retryAfterSeconds;
  }

  public long getRetryAfterSeconds() {
    return retryAfterSeconds;
  }
}
