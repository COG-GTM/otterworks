package com.otterworks.auth.repository;

import com.otterworks.auth.entity.User;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface UserRepository extends JpaRepository<User, UUID> {
  Optional<User> findByEmail(String email);

  List<User> findTop2ByEmailIgnoreCase(String email);

  boolean existsByEmail(String email);
}
