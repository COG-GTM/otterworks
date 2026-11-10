package com.otterworks.auth.exception;

public class InvalidCredentialsException extends IllegalArgumentException {

  public InvalidCredentialsException() {
    super("Invalid credentials");
  }
}
