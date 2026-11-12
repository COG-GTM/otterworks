import { Component } from '@angular/core';
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

@Component({
  selector: 'app-sidebar-host',
  standalone: true,
  imports: [SidebarComponent],
  template: '<app-sidebar></app-sidebar>',
})
class SidebarHostComponent {}

function relativeLuminance(rgb: string): number {
  const [r, g, b] = (rgb.match(/[\d.]+/g) ?? []).slice(0, 3).map(v => {
    const c = Number(v) / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(fg: string, bg: string): number {
  const [lo, hi] = [relativeLuminance(fg), relativeLuminance(bg)].sort((a, b) => a - b);
  return (hi + 0.05) / (lo + 0.05);
}

describe('SidebarComponent nav contrast', () => {
  let fixture: ComponentFixture<SidebarHostComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SidebarHostComponent, RouterTestingModule, NoopAnimationsModule],
    }).compileComponents();
    fixture = TestBed.createComponent(SidebarHostComponent);
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
  });

  afterEach(() => fixture.nativeElement.remove());

  function expectReadable(item: HTMLElement): void {
    const itemStyle = getComputedStyle(item);
    expect(itemStyle.backgroundColor).toMatch(/^rgb\(/);
    for (const el of [item.querySelector('.mat-mdc-list-item-title'), item.querySelector('.mat-icon')]) {
      const fg = getComputedStyle(el as HTMLElement).color;
      expect(fg).toMatch(/^rgb\(/);
      expect(contrastRatio(fg, itemStyle.backgroundColor)).toBeGreaterThanOrEqual(4.5);
    }
  }

  it('renders nav items with opaque colours meeting WCAG AA', () => {
    const items = fixture.nativeElement.querySelectorAll('.mat-mdc-list-item');
    expect(items.length).toBeGreaterThan(0);
    items.forEach((item: HTMLElement) => expectReadable(item));
  });

  it('keeps the active nav item at WCAG AA contrast', () => {
    const item = fixture.nativeElement.querySelector('.mat-mdc-list-item') as HTMLElement;
    item.classList.add('active-link');
    expect(getComputedStyle(item).color).toBe('rgb(242, 192, 120)');
    expectReadable(item);
  });
});
