package com.otterworks.auth.exception;

public class AccountLockedException extends RuntimeException {

  public AccountLockedException() {
    super("Account temporarily locked, try again later");
  }
}
