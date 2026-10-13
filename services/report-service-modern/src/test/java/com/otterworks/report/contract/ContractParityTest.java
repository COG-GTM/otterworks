package com.otterworks.report.contract;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.node.TextNode;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Golden contract test: replays {@code contract/scenarios.json} against this service over HTTP and compares the
 * normalized transcript with {@code contract/legacy-golden.json}, recorded from the legacy Java 8 service via
 * {@code contract/parity.py record}. Normalization rules mirror parity.py.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
class ContractParityTest {

    private static final Pattern LEGACY_TS = Pattern.compile("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}\\+00:00$");
    private static final Pattern CSV_INSTANT = Pattern.compile("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z");
    private static final Set<String> SERVER_TS_KEYS = Set.of("timestamp", "createdAt", "completedAt");
    private static final Set<String> DATE_KEYS = Set.of("dateFrom", "dateTo");
    private static final Set<String> TERMINAL = Set.of("COMPLETED", "FAILED");
    private static final Pattern PLACEHOLDER = Pattern.compile("\\{(\\w+)}");

    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpClient http = HttpClient.newHttpClient();

    @LocalServerPort
    private int port;

    @Test
    void modernTranscriptMatchesLegacyGolden() throws Exception {
        JsonNode scenarios = mapper.readTree(Path.of("contract/scenarios.json").toFile());
        ArrayNode golden = (ArrayNode) mapper.readTree(Path.of("contract/legacy-golden.json").toFile());
        ArrayNode actual = run(scenarios.get("steps"));

        assertEquals(golden.size(), actual.size(), "step count");
        List<String> mismatches = new ArrayList<>();
        for (int i = 0; i < golden.size(); i++) {
            JsonNode expected = golden.get(i);
            JsonNode got = actual.get(i);
            Iterator<String> fields = expected.fieldNames();
            while (fields.hasNext()) {
                String field = fields.next();
                if (!expected.get(field).equals(got.get(field))) {
                    mismatches.add(expected.get("step").asText() + "." + field
                            + "\n    legacy: " + expected.get(field) + "\n    modern: " + got.get(field));
                }
            }
        }
        assertTrue(mismatches.isEmpty(), "Contract drift vs legacy golden:\n" + String.join("\n", mismatches));
    }

    private ArrayNode run(JsonNode steps) throws Exception {
        Map<String, String> ids = new HashMap<>();
        ArrayNode transcript = JsonNodeFactory.instance.arrayNode();
        for (JsonNode step : steps) {
            HttpResponse<byte[]> response = call(step, ids);
            long deadline = System.currentTimeMillis() + 60_000;
            while (step.path("awaitTerminal").asBoolean()
                    && !TERMINAL.contains(mapper.readTree(response.body()).path("status").asText())
                    && System.currentTimeMillis() < deadline) {
                Thread.sleep(250);
                response = call(step, ids);
            }
            if (step.has("capture")) {
                ids.put(step.get("capture").asText(), mapper.readTree(response.body()).get("id").asText());
            }
            String contentType = response.headers().firstValue("Content-Type").orElse(null);
            String disposition = response.headers().firstValue("Content-Disposition").orElse(null);
            String length = response.headers().firstValue("Content-Length").orElse(null);

            ObjectNode entry = transcript.addObject();
            entry.put("step", step.get("name").asText());
            entry.put("request", step.get("method").asText() + " " + step.get("path").asText());
            entry.put("status", response.statusCode());
            entry.put("contentType", contentType);
            entry.put("contentDisposition", disposition == null ? null
                    : disposition.replaceAll("_\\d{8}_\\d{6}\\.", "_<ts>."));
            entry.put("contentLength", length == null || length.equals("0") ? length : "<len>");
            entry.set("body", normalizeBody(contentType, response.body(), step.path("maskDates").asBoolean()));
        }
        return transcript;
    }

    private HttpResponse<byte[]> call(JsonNode step, Map<String, String> ids) throws Exception {
        Matcher matcher = PLACEHOLDER.matcher(step.get("path").asText());
        String path = matcher.replaceAll(m -> ids.get(m.group(1)));
        HttpRequest.Builder request = HttpRequest.newBuilder(URI.create("http://localhost:" + port + path))
                .timeout(Duration.ofSeconds(30))
                .header("Accept", "*/*");
        HttpRequest.BodyPublisher body = HttpRequest.BodyPublishers.noBody();
        if (step.has("json")) {
            body = HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(step.get("json")));
            request.header("Content-Type", "application/json");
        } else if (step.has("raw")) {
            body = HttpRequest.BodyPublishers.ofString(step.get("raw").asText());
            request.header("Content-Type", step.get("contentType").asText());
        }
        request.method(step.get("method").asText(), body);
        return http.send(request.build(), HttpResponse.BodyHandlers.ofByteArray());
    }

    private JsonNode normalizeBody(String contentType, byte[] raw, boolean maskDates) throws Exception {
        if (raw == null || raw.length == 0) {
            return JsonNodeFactory.instance.nullNode();
        }
        String type = contentType == null ? "" : contentType.split(";")[0].trim();
        if (type.endsWith("json")) {
            return normalizeJson(mapper.readTree(raw), maskDates);
        }
        if (type.equals("text/csv")) {
            ArrayNode lines = JsonNodeFactory.instance.arrayNode();
            new String(raw, StandardCharsets.UTF_8).lines()
                    .map(line -> line.replaceAll("^(\"?)# Generated: [^\"]*", "$1# Generated: <ts>"))
                    .map(line -> CSV_INSTANT.matcher(line).replaceAll("<instant>"))
                    .forEach(lines::add);
            return lines;
        }
        ObjectNode binary = JsonNodeFactory.instance.objectNode();
        binary.put("magic", HexFormat.of().formatHex(raw, 0, Math.min(4, raw.length)));
        binary.put("body", "<binary>");
        return binary;
    }

    private JsonNode normalizeJson(JsonNode node, boolean maskDates) {
        if (node.isArray()) {
            ArrayNode out = JsonNodeFactory.instance.arrayNode();
            node.forEach(child -> out.add(normalizeJson(child, maskDates)));
            return out;
        }
        if (!node.isObject()) {
            return node;
        }
        ObjectNode out = JsonNodeFactory.instance.objectNode();
        node.fields().forEachRemaining(field -> {
            String key = field.getKey();
            JsonNode value = field.getValue();
            if (key.equals("id") && value.isIntegralNumber()) {
                out.put(key, "<id>");
            } else if (key.equals("downloadUrl") && value.isTextual()) {
                out.put(key, value.asText().replaceAll("/\\d+/", "/<id>/"));
            } else if (SERVER_TS_KEYS.contains(key) || (maskDates && DATE_KEYS.contains(key))) {
                out.set(key, maskTimestamp(value));
            } else if (key.equals("fileSizeBytes") && value.isIntegralNumber() && value.asLong() > 0) {
                out.put(key, "<size>");
            } else if (key.equals("path") && value.isTextual()) {
                out.put(key, value.asText().replaceAll("/\\d+(?=/|$)", "/<id>"));
            } else {
                out.set(key, normalizeJson(value, maskDates));
            }
        });
        return out;
    }

    private static JsonNode maskTimestamp(JsonNode value) {
        if (value.isNull()) {
            return value;
        }
        return value.isTextual() && LEGACY_TS.matcher(value.asText()).matches()
                ? TextNode.valueOf("<ts>")
                : TextNode.valueOf("<ts-unexpected-format:" + value.asText() + ">");
    }
}
