package com.otterworks.auth.service;

import com.otterworks.auth.dto.UpdateProfileRequest;
import com.otterworks.auth.dto.UserDTO;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
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

  public UserService(UserRepository userRepository) {
    this.userRepository = userRepository;
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

    user = userRepository.save(user);
    log.info("Profile updated for user: {}", userId);
    return UserDTO.fromEntity(user);
  }

  @Transactional
  public UserDTO updateQuota(UUID userId, long quotaBytes) {
    User user =
        userRepository
            .findById(userId)
            .orElseThrow(() -> new IllegalArgumentException("User not found"));
    user.setQuotaBytes(quotaBytes);
    user = userRepository.save(user);
    log.info("Quota updated for user: {} to {} bytes", userId, quotaBytes);
    return UserDTO.fromEntity(user);
  }

  @Transactional(readOnly = true)
  public Page<UserDTO> listUsers(Pageable pageable) {
    return userRepository.findAll(pageable).map(UserDTO::fromEntity);
  }

  @Transactional(readOnly = true)
  public UserDTO findByEmail(String email) {
    return userRepository
        .findByEmail(email)
        .map(UserDTO::fromEntity)
        .orElseThrow(() -> new IllegalArgumentException("User not found with email: " + email));
  }
}
