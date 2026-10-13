# Dependency Notes — collab-service

| Package | Version | Reason | Tracking |
|---------|---------|--------|----------|
| lodash | ^4.18.0 (resolves 4.18.1) | 4.18.1 is the current npm `latest`; the old 4.17.20 pin is gone. Not imported by `src/`. | DEPS-301 |
| y-websocket | ^1.5.4 | v2+ removed `bin/utils` (`setupWSConnection`), which `src/index.ts` uses for the Yjs server. | — |
| uuid | removed | Replaced by Node's built-in `crypto.randomUUID()`. | — |
