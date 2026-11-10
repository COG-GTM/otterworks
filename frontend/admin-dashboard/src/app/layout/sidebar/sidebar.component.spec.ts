import { ComponentFixture, TestBed } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { SidebarComponent } from './sidebar.component';

describe('SidebarComponent', () => {
  let component: SidebarComponent;
  let fixture: ComponentFixture<SidebarComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        SidebarComponent,
        RouterTestingModule,
        NoopAnimationsModule,
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(SidebarComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start expanded', () => {
    expect(component.collapsed).toBeFalse();
  });

  it('should have navigation items', () => {
    expect(component.navItems.length).toBeGreaterThan(0);
  });

  it('should have all expected nav items', () => {
    const labels = component.navItems.map(item => item.label);
    expect(labels).toContain('Dashboard');
    expect(labels).toContain('Users');
    expect(labels).toContain('Audit Logs');
    expect(labels).toContain('Feature Flags');
    expect(labels).toContain('System Health');
    expect(labels).toContain('Announcements');
    expect(labels).toContain('Storage Quotas');
    expect(labels).toContain('Sharing Settings');
    expect(labels).toContain('Analytics');
  });

  it('should toggle collapsed state', () => {
    expect(component.collapsed).toBeFalse();
    component.toggleCollapsed();
    expect(component.collapsed).toBeTrue();
    component.toggleCollapsed();
    expect(component.collapsed).toBeFalse();
  });

  it('should render the sidebar element', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.sidebar')).toBeTruthy();
  });

  it('should render logo text when expanded', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('OtterWorks');
  });
});
