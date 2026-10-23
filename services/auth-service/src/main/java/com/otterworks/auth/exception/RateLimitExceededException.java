package com.otterworks.auth.exception;

public class RateLimitExceededException extends RuntimeException {

  private final long retryAfterSeconds;

  public RateLimitExceededException(long retryAfterSeconds) {
    super("Too many user lookups; try again later");
    this.retryAfterSeconds = retryAfterSeconds;
  }

  public long getRetryAfterSeconds() {
    return retryAfterSeconds;
  }
}
