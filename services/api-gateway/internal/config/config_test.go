package config

import "testing"

func TestValidateRequiresJWTSecret(t *testing.T) {
	cfg := &Config{}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected an error when JWT_SECRET is empty")
	}
}

func TestValidateRejectsKnownPlaceholderSecrets(t *testing.T) {
	for _, secret := range knownInsecureJWTSecrets {
		cfg := &Config{JWTSecret: secret}
		if err := cfg.Validate(); err == nil {
			t.Errorf("expected placeholder secret %q to be rejected", secret)
		}
	}
}

func TestValidateAcceptsGeneratedSecret(t *testing.T) {
	cfg := &Config{JWTSecret: "3f9c1a7e5b2d4c6f8a0e1b3d5f7a9c2e4b6d8f0a1c3e5b7d9f2a4c6e8b0d1f3a"}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}
