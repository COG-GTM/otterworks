package com.otterworks.portal.common;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.NoSuchElementException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** The shared error mapping: exception type → status and {@code {"error","message"}} body. */
class GlobalExceptionHandlerTest {

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new ThrowingController())
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void noSuchElementMapsTo404WithReasonAndMessage() throws Exception {
        mockMvc.perform(get("/missing"))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(content().json(
                        "{\"error\":\"Not Found\",\"message\":\"Announcement not found: 42\"}", true));
    }

    @Test
    void illegalArgumentMapsTo400WithReasonAndMessage() throws Exception {
        mockMvc.perform(get("/invalid"))
                .andExpect(status().isBadRequest())
                .andExpect(content().json(
                        "{\"error\":\"Bad Request\",\"message\":\"Rating must be between 1 and 5\"}", true));
    }

    @Test
    void subclassesOfIllegalArgumentAreMappedToo() throws Exception {
        mockMvc.perform(get("/number-format"))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"error\":\"Bad Request\",\"message\":\"For input string: \\\"x\\\"\"}", true));
    }

    @Test
    void bodyKeepsErrorThenMessageFieldOrder() throws Exception {
        mockMvc.perform(get("/missing"))
                .andExpect(content().string(
                        "{\"error\":\"Not Found\",\"message\":\"Announcement not found: 42\"}"));
    }

    @Test
    void nullMessageIsRenderedAsJsonNull() throws Exception {
        mockMvc.perform(get("/missing-without-message"))
                .andExpect(status().isNotFound())
                .andExpect(content().string("{\"error\":\"Not Found\",\"message\":null}"));
    }

    @Test
    void otherExceptionsAreNotMapped() {
        assertThrows(
                Exception.class, () -> mockMvc.perform(get("/unmapped")));
    }

    @RestController
    static class ThrowingController {

        @GetMapping("/missing")
        String missing() {
            throw new NoSuchElementException("Announcement not found: 42");
        }

        @GetMapping("/missing-without-message")
        String missingWithoutMessage() {
            throw new NoSuchElementException();
        }

        @GetMapping("/invalid")
        String invalid() {
            throw new IllegalArgumentException("Rating must be between 1 and 5");
        }

        @GetMapping("/number-format")
        String numberFormat() {
            return String.valueOf(Integer.parseInt("x"));
        }

        @GetMapping("/unmapped")
        String unmapped() {
            throw new IllegalStateException("not part of the mapping");
        }
    }
}
