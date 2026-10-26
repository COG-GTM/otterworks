package config

import (
	"strings"
	"testing"
)

func TestValidateJWTSecret(t *testing.T) {
	cases := map[string]struct {
		secret  string
		wantErr string
	}{
		"unset":     {"", "required"},
		"blank":     {"   ", "required"},
		"published": {"otterworks-local-dev-jwt-secret-change-me-in-production", "published"},
		"short":     {strings.Repeat("a", MinJWTSecretBytes-1), "at least"},
		"strong":    {strings.Repeat("a", MinJWTSecretBytes), ""},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			err := (&Config{JWTSecret: tc.secret}).Validate()
			if tc.wantErr == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), tc.wantErr) {
				t.Fatalf("want error containing %q, got %v", tc.wantErr, err)
			}
		})
	}
	for secret := range publishedJWTSecrets {
		if err := (&Config{JWTSecret: secret}).Validate(); err == nil {
			t.Errorf("published secret %q accepted", secret)
		}
	}
}
