package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.otterworks.auth.audit.AuditClient;
import com.otterworks.auth.audit.AuditEvent;
import com.otterworks.auth.dto.UpdateProfileRequest;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
import java.util.EnumSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

@ExtendWith(MockitoExtension.class)
class UserServiceTest {

  private static final String ADMIN_ID = UUID.randomUUID().toString();

  @Mock private UserRepository userRepository;
  @Mock private AuditClient auditClient;

  @InjectMocks private UserService userService;

  private User target;

  @BeforeEach
  void setUp() {
    target = new User();
    target.setId(UUID.randomUUID());
    target.setEmail("target@otterworks.dev");
    target.setDisplayName("Target");
    target.setPasswordHash("$2a$12$encodedpassword");
    target.setRoles(EnumSet.of(User.Role.USER));

    SecurityContextHolder.getContext()
        .setAuthentication(
            new UsernamePasswordAuthenticationToken(
                ADMIN_ID, null, List.of(new SimpleGrantedAuthority("ROLE_ADMIN"))));
  }

  @AfterEach
  void clearContext() {
    SecurityContextHolder.clearContext();
  }

  private AuditEvent singleEvent() {
    ArgumentCaptor<AuditEvent> captor = ArgumentCaptor.forClass(AuditEvent.class);
    verify(auditClient).emit(captor.capture());
    return captor.getValue();
  }

  @Test
  void updateRoles_emitsPermissionChangeWithBeforeAndAfter() {
    when(userRepository.findById(target.getId())).thenReturn(Optional.of(target));
    when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));

    userService.updateRoles(target.getId(), Set.of(User.Role.EDITOR, User.Role.USER));

    assertThat(target.getRoles()).containsExactlyInAnyOrder(User.Role.EDITOR, User.Role.USER);
    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("permission.change");
    assertThat(event.getOutcome()).isEqualTo("success");
    assertThat(event.getUserId()).isEqualTo(ADMIN_ID);
    assertThat(event.getActorType()).isEqualTo("admin");
    assertThat(event.getResourceType()).isEqualTo("user");
    assertThat(event.getResourceId()).isEqualTo(target.getId().toString());
    assertThat(event.getDetails())
        .containsEntry("before", "USER")
        .containsEntry("after", "EDITOR,USER");
  }

  @Test
  void updateRoles_unknownUser_emitsNothing() {
    UUID missing = UUID.randomUUID();
    when(userRepository.findById(missing)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.updateRoles(missing, Set.of(User.Role.ADMIN)))
        .isInstanceOf(IllegalArgumentException.class);
    verifyNoInteractions(auditClient);
  }

  @Test
  void listUsers_emitsDirectoryExport() {
    Pageable pageable = PageRequest.of(0, 10);
    when(userRepository.findAll(pageable)).thenReturn(new PageImpl<>(List.of(target)));

    userService.listUsers(pageable);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("export");
    assertThat(event.getResourceType()).isEqualTo("user_directory");
    assertThat(event.getResourceId()).isEqualTo("all");
    assertThat(event.getOutcome()).isEqualTo("success");
    assertThat(event.getUserId()).isEqualTo(ADMIN_ID);
    assertThat(event.getDetails()).containsEntry("returned", "1").containsEntry("size", "10");
    assertThat(event.toString()).doesNotContain("$2a$");
  }

  @Test
  void lookup_found_emitsDirectoryExport() {
    when(userRepository.findByEmail("target@otterworks.dev")).thenReturn(Optional.of(target));

    userService.findByEmail("target@otterworks.dev");

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("export");
    assertThat(event.getResourceType()).isEqualTo("user_directory");
    assertThat(event.getResourceId()).isEqualTo(target.getId().toString());
    assertThat(event.getOutcome()).isEqualTo("success");
    assertThat(event.getDetails())
        .containsEntry("query", "lookup")
        .containsEntry("lookupEmail", "target@otterworks.dev");
  }

  @Test
  void lookup_notFound_emitsFailedExport() {
    when(userRepository.findByEmail("nobody@otterworks.dev")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.findByEmail("nobody@otterworks.dev"))
        .isInstanceOf(IllegalArgumentException.class);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("export");
    assertThat(event.getOutcome()).isEqualTo("failure");
    assertThat(event.getResourceId()).isEqualTo("unknown");
    assertThat(event.getDetails()).containsEntry("returned", "0");
  }

  @Test
  void updateProfile_emailChange_emitsEmailChangeSuccess() {
    when(userRepository.findById(target.getId())).thenReturn(Optional.of(target));
    when(userRepository.existsByEmail("new@otterworks.dev")).thenReturn(false);
    when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setEmail("new@otterworks.dev");

    userService.updateProfile(target.getId(), request);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.profile.email_change");
    assertThat(event.getOutcome()).isEqualTo("success");
    assertThat(event.getUserId()).isEqualTo(target.getId().toString());
    assertThat(event.getResourceId()).isEqualTo(target.getId().toString());
    assertThat(event.getDetails())
        .containsEntry("previousEmail", "target@otterworks.dev")
        .containsEntry("newEmail", "new@otterworks.dev");
  }

  @Test
  void updateProfile_emailTaken_emitsFailureAndDoesNotSave() {
    when(userRepository.findById(target.getId())).thenReturn(Optional.of(target));
    when(userRepository.existsByEmail("taken@otterworks.dev")).thenReturn(true);
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setEmail("taken@otterworks.dev");

    assertThatThrownBy(() -> userService.updateProfile(target.getId(), request))
        .isInstanceOf(IllegalArgumentException.class);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.profile.email_change");
    assertThat(event.getOutcome()).isEqualTo("failure");
    assertThat(event.getDetails()).containsEntry("reason", "email_taken");
    verify(userRepository, never()).save(any(User.class));
  }

  @Test
  void updateProfile_withoutEmailChange_emitsNothing() {
    when(userRepository.findById(target.getId())).thenReturn(Optional.of(target));
    when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Renamed");
    request.setEmail("target@otterworks.dev");

    userService.updateProfile(target.getId(), request);

    verifyNoInteractions(auditClient);
  }
}
