package config

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

// OTW-45: GET/PUT /api/v1/workspace/share-policy are served by document-service.
func TestServiceRoutesWorkspaceSharePolicyGoesToDocumentService(t *testing.T) {
	c := &Config{DocumentServiceURL: "http://document-service:8083"}

	routes := c.ServiceRoutes()

	assert.Equal(t, "http://document-service:8083", routes["/api/v1/workspace/share-policy"])
	_, broad := routes["/api/v1/workspace"]
	assert.False(t, broad, "only the share-policy sub-path is routed to document-service")
}
