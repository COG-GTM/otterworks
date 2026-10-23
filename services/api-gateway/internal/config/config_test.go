package config

import "testing"

func TestValidateRejectsMissingSecret(t *testing.T) {
	if err := (&Config{}).Validate(); err == nil {
		t.Fatal("expected an error for an empty JWT_SECRET")
	}
}

func TestValidateRejectsPublishedSecrets(t *testing.T) {
	for _, secret := range PublishedJWTSecrets {
		if err := (&Config{JWTSecret: secret}).Validate(); err == nil {
			t.Errorf("expected %q to be rejected", secret)
		}
	}
}

func TestValidateAcceptsRandomSecret(t *testing.T) {
	cfg := &Config{JWTSecret: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}
