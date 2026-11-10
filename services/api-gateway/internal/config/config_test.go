package config

import "testing"

func TestServiceRoutesProxyShareLinksToDocumentService(t *testing.T) {
	cfg := &Config{DocumentServiceURL: "http://document-service:8083"}
	if got := cfg.ServiceRoutes()["/api/v1/share-links"]; got != cfg.DocumentServiceURL {
		t.Fatalf("/api/v1/share-links routes to %q, want %q", got, cfg.DocumentServiceURL)
	}
}
