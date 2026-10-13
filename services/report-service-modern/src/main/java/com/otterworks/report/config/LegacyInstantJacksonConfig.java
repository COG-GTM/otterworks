package com.otterworks.report.config;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.SerializerProvider;
import com.fasterxml.jackson.databind.deser.std.StdScalarDeserializer;
import com.fasterxml.jackson.databind.module.SimpleModule;
import com.fasterxml.jackson.databind.ser.std.StdScalarSerializer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.io.IOException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeFormatterBuilder;
import java.time.format.DateTimeParseException;
import java.time.temporal.ChronoField;
import java.time.temporal.ChronoUnit;
import java.util.regex.Pattern;

/**
 * Keeps the JSON wire format of timestamps identical to the legacy service, which serialized
 * {@code java.util.Date} through Jackson's {@code StdDateFormat}: output is
 * {@code yyyy-MM-dd'T'HH:mm:ss.SSS+00:00}, input accepts epoch millis, ISO-8601 (with or without
 * offset/fraction), date-only and RFC-1123 strings.
 */
@Configuration
public class LegacyInstantJacksonConfig {

    static final DateTimeFormatter WRITE_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSxxx").withZone(ZoneOffset.UTC);

    private static final Pattern EPOCH_MILLIS = Pattern.compile("-?\\d+");

    private static final DateTimeFormatter ISO_LOCAL = new DateTimeFormatterBuilder()
            .append(DateTimeFormatter.ISO_LOCAL_DATE)
            .appendLiteral('T')
            .appendPattern("HH:mm[:ss]")
            .optionalStart().appendFraction(ChronoField.NANO_OF_SECOND, 1, 9, true).optionalEnd()
            .optionalStart().appendOffset("+HH:MM", "Z").optionalEnd()
            .optionalStart().appendOffset("+HHMM", "Z").optionalEnd()
            .optionalStart().appendOffset("+HH", "Z").optionalEnd()
            .toFormatter();

    @Bean
    public SimpleModule legacyInstantModule() {
        SimpleModule module = new SimpleModule("legacy-instant-format");
        module.addSerializer(Instant.class, new Serializer());
        module.addDeserializer(Instant.class, new Deserializer());
        return module;
    }

    public static String format(Instant instant) {
        return WRITE_FORMAT.format(instant);
    }

    public static Instant parse(String text) {
        String value = text.trim();
        if (EPOCH_MILLIS.matcher(value).matches()) {
            return Instant.ofEpochMilli(Long.parseLong(value));
        }
        if (value.length() == 10) {
            return LocalDate.parse(value).atStartOfDay(ZoneOffset.UTC).toInstant();
        }
        try {
            var parsed = ISO_LOCAL.parseBest(value, OffsetDateTime::from, LocalDateTime::from);
            if (parsed instanceof OffsetDateTime odt) {
                return odt.toInstant().truncatedTo(ChronoUnit.MILLIS);
            }
            return ((LocalDateTime) parsed).toInstant(ZoneOffset.UTC).truncatedTo(ChronoUnit.MILLIS);
        } catch (DateTimeParseException isoFailure) {
            return ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant();
        }
    }

    static final class Serializer extends StdScalarSerializer<Instant> {
        Serializer() {
            super(Instant.class);
        }

        @Override
        public void serialize(Instant value, JsonGenerator gen, SerializerProvider provider) throws IOException {
            gen.writeString(format(value));
        }
    }

    static final class Deserializer extends StdScalarDeserializer<Instant> {
        Deserializer() {
            super(Instant.class);
        }

        @Override
        public Instant deserialize(JsonParser p, DeserializationContext ctxt) throws IOException {
            if (p.hasToken(JsonToken.VALUE_NUMBER_INT)) {
                return Instant.ofEpochMilli(p.getLongValue());
            }
            if (p.hasToken(JsonToken.VALUE_STRING)) {
                String text = p.getText();
                if (text.isBlank()) {
                    return null;
                }
                try {
                    return parse(text);
                } catch (DateTimeParseException | NumberFormatException e) {
                    return (Instant) ctxt.handleWeirdStringValue(Instant.class, text,
                            "not a valid timestamp (expected epoch millis or ISO-8601)");
                }
            }
            return (Instant) ctxt.handleUnexpectedToken(Instant.class, p);
        }
    }
}
