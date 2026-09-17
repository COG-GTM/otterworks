package com.otterworks.auth.repository;

import com.otterworks.auth.entity.User;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

@Repository
public interface UserRepository extends JpaRepository<User, UUID> {
  Optional<User> findByEmail(String email);

  boolean existsByEmail(String email);

  @Modifying(clearAutomatically = true, flushAutomatically = true)
  @Query(
      "UPDATE User u SET u.failedLoginAttempts = :attempts, u.lastFailedLoginAt = :failedAt, "
          + "u.lockoutUntil = :lockoutUntil, u.updatedAt = :failedAt WHERE u.id = :id")
  void recordFailedLogin(
      @Param("id") UUID id,
      @Param("attempts") int attempts,
      @Param("failedAt") Instant failedAt,
      @Param("lockoutUntil") Instant lockoutUntil);
}
