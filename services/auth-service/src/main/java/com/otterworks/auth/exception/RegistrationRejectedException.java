package com.otterworks.auth.exception;

/**
 * Thrown when a registration cannot be completed. The client-facing message is deliberately the
 * same for every cause (including an email that already has an account) so the public register
 * endpoint cannot be used to discover which emails are registered.
 */
public class RegistrationRejectedException extends RuntimeException {

  public static final String CLIENT_MESSAGE =
      "Unable to complete registration with the provided details";

  public RegistrationRejectedException() {
    super(CLIENT_MESSAGE);
  }
}
