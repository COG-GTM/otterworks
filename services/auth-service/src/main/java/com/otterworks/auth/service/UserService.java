package com.otterworks.auth.service;

import com.otterworks.auth.audit.AuditActor;
import com.otterworks.auth.audit.AuditClient;
import com.otterworks.auth.audit.AuditEvent;
import com.otterworks.auth.dto.UpdateProfileRequest;
import com.otterworks.auth.dto.UserDTO;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class UserService {

  private static final Logger log = LoggerFactory.getLogger(UserService.class);

  private final UserRepository userRepository;
  private final AuditClient auditClient;

  public UserService(UserRepository userRepository, AuditClient auditClient) {
    this.userRepository = userRepository;
    this.auditClient = auditClient;
  }

  @Transactional(readOnly = true)
  public UserDTO getProfile(UUID userId) {
    User user =
        userRepository
            .findById(userId)
            .orElseThrow(() -> new IllegalArgumentException("User not found"));
    return UserDTO.fromEntity(user);
  }

  @Transactional
  public UserDTO updateProfile(UUID userId, UpdateProfileRequest request) {
    User user =
        userRepository
            .findById(userId)
            .orElseThrow(() -> new IllegalArgumentException("User not found"));

    if (request.getDisplayName() != null) {
      user.setDisplayName(request.getDisplayName());
    }
    if (request.getAvatarUrl() != null) {
      user.setAvatarUrl(request.getAvatarUrl());
    }
    String previousEmail = user.getEmail();
    String newEmail = request.getEmail();
    boolean emailChanged = newEmail != null && !newEmail.equals(previousEmail);
    if (emailChanged) {
      if (userRepository.existsByEmail(newEmail)) {
        auditClient.emit(
            emailChange(
                userId,
                AuditEvent.OUTCOME_FAILURE,
                Map.of(
                    "reason",
                    "email_taken",
                    "previousEmail",
                    String.valueOf(previousEmail),
                    "attemptedEmail",
                    newEmail)));
        throw new IllegalArgumentException("Email already registered");
      }
      user.setEmail(newEmail);
    }

    user = userRepository.save(user);
    log.info("Profile updated for user: {}", userId);
    if (emailChanged) {
      auditClient.emit(
          emailChange(
              userId,
              AuditEvent.OUTCOME_SUCCESS,
              Map.of("previousEmail", String.valueOf(previousEmail), "newEmail", newEmail)));
    }
    return UserDTO.fromEntity(user);
  }

  @Transactional
  public UserDTO updateRoles(UUID userId, Set<User.Role> roles) {
    User user =
        userRepository
            .findById(userId)
            .orElseThrow(() -> new IllegalArgumentException("User not found"));

    String before = AuthService.rolesToString(user.getRoles());
    user.setRoles(EnumSet.copyOf(roles));
    user = userRepository.save(user);
    String after = AuthService.rolesToString(user.getRoles());

    log.info("Roles updated for user {}: [{}] -> [{}]", userId, before, after);
    auditClient.emit(
        AuditEvent.builder()
            .userId(AuditActor.currentUserId())
            .actorType(AuditActor.currentActorType())
            .action("permission.change")
            .resourceType("user")
            .resourceId(userId.toString())
            .outcome(AuditEvent.OUTCOME_SUCCESS)
            .details(Map.of("before", before, "after", after, "reason", "admin_update"))
            .build());
    return UserDTO.fromEntity(user);
  }

  @Transactional(readOnly = true)
  public Page<UserDTO> listUsers(Pageable pageable) {
    Page<UserDTO> page = userRepository.findAll(pageable).map(UserDTO::fromEntity);
    Map<String, String> details = new LinkedHashMap<>();
    details.put("query", "list");
    details.put("returned", String.valueOf(page.getNumberOfElements()));
    if (pageable.isPaged()) {
      details.put("page", String.valueOf(pageable.getPageNumber()));
      details.put("size", String.valueOf(pageable.getPageSize()));
    }
    auditClient.emit(directoryExport("all", AuditEvent.OUTCOME_SUCCESS, details));
    return page;
  }

  @Transactional(readOnly = true)
  public UserDTO findByEmail(String email) {
    Optional<User> found = userRepository.findByEmail(email);
    auditClient.emit(
        directoryExport(
            found.map(u -> u.getId().toString()).orElse("unknown"),
            found.isPresent() ? AuditEvent.OUTCOME_SUCCESS : AuditEvent.OUTCOME_FAILURE,
            Map.of(
                "query",
                "lookup",
                "lookupEmail",
                String.valueOf(email),
                "returned",
                found.isPresent() ? "1" : "0")));
    return found
        .map(UserDTO::fromEntity)
        .orElseThrow(() -> new IllegalArgumentException("User not found with email: " + email));
  }

  private static AuditEvent emailChange(UUID userId, String outcome, Map<String, String> details) {
    return AuditEvent.builder()
        .userId(userId.toString())
        .actorType(AuditActor.TYPE_USER)
        .action("auth.profile.email_change")
        .resourceType("user")
        .resourceId(userId.toString())
        .outcome(outcome)
        .details(details)
        .build();
  }

  private static AuditEvent directoryExport(
      String resourceId, String outcome, Map<String, String> details) {
    return AuditEvent.builder()
        .userId(AuditActor.currentUserId())
        .actorType(AuditActor.currentActorType())
        .action("export")
        .resourceType("user_directory")
        .resourceId(resourceId)
        .outcome(outcome)
        .details(details)
        .build();
  }
}
