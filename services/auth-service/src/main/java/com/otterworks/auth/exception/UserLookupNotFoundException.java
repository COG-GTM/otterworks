package com.otterworks.auth.exception;

public class UserLookupNotFoundException extends RuntimeException {

  public UserLookupNotFoundException() {
    super("User not found");
  }
}
