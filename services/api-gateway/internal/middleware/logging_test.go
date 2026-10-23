package middleware

import "testing"

func TestRedactQuery(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want string
	}{
		{"empty", "", ""},
		{"no credentials", "page=2&q=otter", "page=2&q=otter"},
		{"token", "token=eyJhbGciOi.eyJzdWIi.sig", "token=REDACTED"},
		{"mixed order kept", "room=doc-1&token=abc&x=1", "room=doc-1&token=REDACTED&x=1"},
		{"case insensitive", "Access_Token=abc", "Access_Token=REDACTED"},
		{"encoded key", "%74oken=abc", "%74oken=REDACTED"},
		{"refresh and jwt", "refresh_token=a&jwt=b&id_token=c", "refresh_token=REDACTED&jwt=REDACTED&id_token=REDACTED"},
		{"bare key", "token", "token"},
		{"similar name untouched", "tokenizer=abc", "tokenizer=abc"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := RedactQuery(tc.in); got != tc.want {
				t.Fatalf("RedactQuery(%q) = %q, want %q", tc.in, got, tc.want)
			}
		})
	}
}
