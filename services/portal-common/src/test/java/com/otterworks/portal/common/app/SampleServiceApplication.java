package com.otterworks.portal.common.app;

import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** A minimal service that only depends on portal-common, as each extracted service will. */
@SpringBootApplication
public class SampleServiceApplication {

    @RestController
    static class SampleController {

        @GetMapping("/api/samples")
        String samples(@RequestParam(defaultValue = "1") int page) {
            return "page " + page;
        }
    }
}
