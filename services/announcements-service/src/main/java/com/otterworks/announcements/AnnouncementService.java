package com.otterworks.announcements;

import java.util.List;
import java.util.NoSuchElementException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AnnouncementService {

    private final AnnouncementRepository repository;

    public AnnouncementService(AnnouncementRepository repository) {
        this.repository = repository;
    }

    @Transactional
    public Announcement create(String title, String body, boolean published) {
        return repository.save(new Announcement(title, body, published));
    }

    @Transactional(readOnly = true)
    public List<Announcement> listPublished() {
        return repository.findByPublishedTrueOrderByCreatedAtDesc();
    }

    @Transactional(readOnly = true)
    public List<Announcement> listAll() {
        return repository.findAll();
    }

    @Transactional(readOnly = true)
    public Announcement get(Long id) {
        return repository.findById(id)
                .orElseThrow(() -> new NoSuchElementException("announcement " + id + " not found"));
    }

    @Transactional
    public Announcement publish(Long id) {
        Announcement announcement = get(id);
        announcement.setPublished(true);
        return repository.save(announcement);
    }
}
