package com.otterworks.auth.exception;

/**
 * A rejected request whose message is written for the caller and safe to return verbatim. Any other
 * {@link IllegalArgumentException} may carry internal detail and is answered generically.
 */
public class BadRequestException extends IllegalArgumentException {

  public BadRequestException(String message) {
    super(message);
  }
}
