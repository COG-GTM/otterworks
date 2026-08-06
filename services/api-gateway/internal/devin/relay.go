// Package devin relays upload-failure incidents to the Devin API so a triage
// session is started automatically. The API key stays server-side: the
// frontend only posts the incident to this endpoint, never to Devin directly.
package devin

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/rs/zerolog"
)

const devinSessionsURL = "https://api.devin.ai/v1/sessions"

const (
	maxReportBodyBytes = 16 << 10 // 16 KiB
	maxFieldLen        = 256
)

// Relay accepts upload-failure incident reports and opens a Devin triage
// session, at most once per cooldown window so a burst of failed uploads does
// not spawn dozens of sessions.
type Relay struct {
	apiKey   string
	cooldown time.Duration
	logger   zerolog.Logger
	client   *http.Client

	mu          sync.Mutex
	lastTrigger time.Time
}

func NewRelay(apiKey string, cooldown time.Duration, logger zerolog.Logger) *Relay {
	return &Relay{
		apiKey:   apiKey,
		cooldown: cooldown,
		logger:   logger,
		client:   &http.Client{Timeout: 15 * time.Second},
	}
}

type uploadFailureReport struct {
	FileName   string `json:"file_name"`
	HTTPStatus *int   `json:"http_status"`
	Message    string `json:"message"`
}

// UploadFailureHandler handles POST /api/v1/incidents/upload-failure.
// It always returns 202: the caller's upload-failure UI must work whether or
// not a Devin session could be created.
func (r *Relay) UploadFailureHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		var report uploadFailureReport
		if err := json.NewDecoder(http.MaxBytesReader(w, req.Body, maxReportBodyBytes)).Decode(&report); err != nil {
			http.Error(w, "invalid JSON body", http.StatusBadRequest)
			return
		}
		report.FileName = truncate(report.FileName, maxFieldLen)
		report.Message = truncate(report.Message, maxFieldLen)
		if report.HTTPStatus != nil && (*report.HTTPStatus < 100 || *report.HTTPStatus > 599) {
			report.HTTPStatus = nil
		}

		go r.triggerTriage(report)

		w.WriteHeader(http.StatusAccepted)
	}
}

func (r *Relay) triggerTriage(report uploadFailureReport) {
	if r.apiKey == "" {
		r.logger.Warn().Msg("DEVIN_API_KEY not configured; skipping Devin triage session for upload failure")
		return
	}

	r.mu.Lock()
	if time.Since(r.lastTrigger) < r.cooldown {
		r.mu.Unlock()
		r.logger.Info().Msg("Devin triage cooldown active; not creating another session")
		return
	}
	r.lastTrigger = time.Now()
	r.mu.Unlock()

	status := "unknown"
	if report.HTTPStatus != nil {
		status = fmt.Sprintf("%d", *report.HTTPStatus)
	}
	prompt := fmt.Sprintf(
		"Triage a file upload failure in the COG-GTM/otterworks repo. "+
			"A user upload of %q failed with HTTP status %s (error: %s) from service=file-service. "+
			"Start with the runbook at docs/runbooks/file-upload-failure.md. "+
			"Investigate the file-service upload path, identify the root cause, and report your findings.",
		report.FileName, status, report.Message,
	)

	body, err := json.Marshal(map[string]string{"prompt": prompt})
	if err != nil {
		r.logger.Error().Err(err).Msg("failed to marshal Devin session request")
		return
	}

	httpReq, err := http.NewRequest(http.MethodPost, devinSessionsURL, bytes.NewReader(body))
	if err != nil {
		r.logger.Error().Err(err).Msg("failed to build Devin session request")
		return
	}
	httpReq.Header.Set("Authorization", "Bearer "+r.apiKey)
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := r.client.Do(httpReq)
	if err != nil {
		r.logger.Error().Err(err).Msg("failed to create Devin triage session")
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		r.logger.Error().Int("status", resp.StatusCode).Msg("Devin API rejected session creation")
		return
	}
	var out struct {
		SessionID string `json:"session_id"`
		URL       string `json:"url"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		r.logger.Warn().Int("status", resp.StatusCode).Msg("Devin session created but response body could not be decoded")
		return
	}
	r.logger.Info().
		Str("session_id", out.SessionID).
		Str("session_url", out.URL).
		Msg("Devin triage session created for upload failure")
}

func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}
