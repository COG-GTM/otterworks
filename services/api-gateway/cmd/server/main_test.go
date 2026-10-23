package main

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/config"
	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/proxy"
)

func TestRoutePrefixes_ProtectsEveryConfiguredRoute(t *testing.T) {
	var routes []proxy.Route
	for prefix, target := range config.Load().ServiceRoutes() {
		routes = append(routes, proxy.Route{Prefix: prefix, TargetURL: target})
	}
	prefixes := routePrefixes(routes)
	assert.Len(t, prefixes, len(routes))
	for _, r := range routes {
		assert.Contains(t, prefixes, r.Prefix)
	}
}

func TestRoutePrefixes_Empty(t *testing.T) {
	assert.Empty(t, routePrefixes(nil))
}
