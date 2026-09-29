package com.otterworks.servicetemplate.example;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/example-items")
public class ExampleItemController {

    public record CreateExampleItem(@NotBlank @Size(max = 120) String name) {}

    public record ExampleItemView(Long id, String name) {
        static ExampleItemView of(ExampleItem item) {
            return new ExampleItemView(item.getId(), item.getName());
        }
    }

    private final ExampleItemRepository repository;

    public ExampleItemController(ExampleItemRepository repository) {
        this.repository = repository;
    }

    @GetMapping
    public List<ExampleItemView> list() {
        return repository.findAll().stream().map(ExampleItemView::of).toList();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ExampleItemView create(@Valid @RequestBody CreateExampleItem request) {
        return ExampleItemView.of(repository.save(new ExampleItem(request.name())));
    }
}
