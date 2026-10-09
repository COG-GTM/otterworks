package com.otterworks.report.security;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

/**
 * The authenticated caller is not allowed to perform the requested report operation.
 */
@ResponseStatus(HttpStatus.FORBIDDEN)
public class ReportAccessDeniedException extends RuntimeException {

    public ReportAccessDeniedException(String message) {
        super(message);
    }
}
