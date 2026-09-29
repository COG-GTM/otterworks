package com.otterworks.servicetemplate.example;

import org.springframework.data.jpa.repository.JpaRepository;

public interface ExampleItemRepository extends JpaRepository<ExampleItem, Long> {}
