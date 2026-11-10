package config

import "testing"

func TestServiceRoutesFolderShareLinksGoToDocumentService(t *testing.T) {
	cfg := &Config{DocumentServiceURL: "http://document-service:8083", FileServiceURL: "http://file-service:8082"}
	routes := cfg.ServiceRoutes()
	if got := routes["/api/v1/folder-share-links"]; got != cfg.DocumentServiceURL {
		t.Fatalf("/api/v1/folder-share-links -> %q, want document-service", got)
	}
	if got := routes["/api/v1/folders"]; got != cfg.FileServiceURL {
		t.Fatalf("/api/v1/folders -> %q, want file-service", got)
	}
}
