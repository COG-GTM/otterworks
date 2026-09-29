package com.otterworks.feedback;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** Feedback bounded context, extracted from legacy-portal. Owns the {@code feedback} schema. */
@SpringBootApplication
public class FeedbackServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(FeedbackServiceApplication.class, args);
    }
}
