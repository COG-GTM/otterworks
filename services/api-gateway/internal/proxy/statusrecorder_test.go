package proxy

import (
	"bufio"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// plainWriter implements only http.ResponseWriter, so Flush is a no-op and
// Hijack must report that hijacking is unsupported.
type plainWriter struct {
	header http.Header
	body   []byte
	status int
}

func newPlainWriter() *plainWriter {
	return &plainWriter{header: http.Header{}, status: http.StatusOK}
}

func (w *plainWriter) Header() http.Header { return w.header }

func (w *plainWriter) Write(b []byte) (int, error) {
	w.body = append(w.body, b...)
	return len(b), nil
}

func (w *plainWriter) WriteHeader(code int) { w.status = code }

// hijackableWriter additionally implements http.Hijacker so the success path
// of statusRecorder.Hijack can be exercised.
type hijackableWriter struct {
	*plainWriter
	conn     net.Conn
	hijacked bool
}

func (w *hijackableWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	w.hijacked = true
	return w.conn, bufio.NewReadWriter(bufio.NewReader(w.conn), bufio.NewWriter(w.conn)), nil
}

func TestStatusRecorder_WriteHeaderKeepsFirstStatus(t *testing.T) {
	inner := newPlainWriter()
	rec := &statusRecorder{ResponseWriter: inner, statusCode: http.StatusOK}

	rec.WriteHeader(http.StatusTeapot)
	rec.WriteHeader(http.StatusInternalServerError)

	assert.Equal(t, http.StatusTeapot, rec.statusCode, "only the first status is recorded")
	assert.Equal(t, http.StatusInternalServerError, inner.status, "later writes still reach the wrapped writer")
}

func TestStatusRecorder_WriteImpliesOK(t *testing.T) {
	inner := newPlainWriter()
	rec := &statusRecorder{ResponseWriter: inner, statusCode: http.StatusOK}

	n, err := rec.Write([]byte("hello"))
	require.NoError(t, err)
	assert.Equal(t, 5, n)
	assert.Equal(t, "hello", string(inner.body))
	assert.True(t, rec.written, "an implicit 200 counts as written")

	// A WriteHeader after the body must not overwrite the implied 200.
	rec.WriteHeader(http.StatusInternalServerError)
	assert.Equal(t, http.StatusOK, rec.statusCode)
}

func TestStatusRecorder_Unwrap(t *testing.T) {
	inner := newPlainWriter()
	rec := &statusRecorder{ResponseWriter: inner, statusCode: http.StatusOK}

	assert.Same(t, inner, rec.Unwrap())
}

func TestStatusRecorder_FlushDelegatesWhenSupported(t *testing.T) {
	flushable := httptest.NewRecorder()
	rec := &statusRecorder{ResponseWriter: flushable, statusCode: http.StatusOK}

	_, err := rec.Write([]byte("chunk"))
	require.NoError(t, err)
	rec.Flush()

	assert.True(t, flushable.Flushed)
}

func TestStatusRecorder_FlushIsNoOpWhenUnsupported(t *testing.T) {
	rec := &statusRecorder{ResponseWriter: newPlainWriter(), statusCode: http.StatusOK}

	assert.NotPanics(t, rec.Flush)
}

func TestStatusRecorder_HijackDelegatesWhenSupported(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	inner := &hijackableWriter{plainWriter: newPlainWriter(), conn: server}
	rec := &statusRecorder{ResponseWriter: inner, statusCode: http.StatusOK}

	conn, rw, err := rec.Hijack()

	require.NoError(t, err)
	assert.True(t, inner.hijacked)
	assert.Same(t, server, conn)
	assert.NotNil(t, rw)
}

func TestStatusRecorder_HijackFailsWhenUnsupported(t *testing.T) {
	rec := &statusRecorder{ResponseWriter: newPlainWriter(), statusCode: http.StatusOK}

	conn, rw, err := rec.Hijack()

	require.Error(t, err)
	assert.Contains(t, err.Error(), "does not support hijacking")
	assert.Nil(t, conn)
	assert.Nil(t, rw)
}
