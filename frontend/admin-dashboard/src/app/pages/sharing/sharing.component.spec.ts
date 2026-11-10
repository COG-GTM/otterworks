import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { SharingComponent } from './sharing.component';

const POLICY_URL = '/api/v1/admin/sharing_policy';

describe('SharingComponent', () => {
  let component: SharingComponent;
  let fixture: ComponentFixture<SharingComponent>;
  let http: HttpTestingController;

  const text = () => (fixture.nativeElement as HTMLElement).textContent ?? '';
  const query = <T extends Element>(selector: string) =>
    (fixture.nativeElement as HTMLElement).querySelector<T>(selector);
  const saveButton = () => query<HTMLButtonElement>('[data-testid="save"]')!;

  function loadPolicy(body: object = { default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 }): void {
    fixture.detectChanges();
    http.expectOne({ method: 'GET', url: POLICY_URL }).flush(body);
    fixture.detectChanges();
  }

  function setValues(values: { defaultExpiryDays?: number | null; minExpiryDays?: number | null; maxExpiryDays?: number | null }): void {
    component.form.patchValue(values);
    component.form.markAsDirty();
    component.form.markAllAsTouched();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SharingComponent, HttpClientTestingModule, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(SharingComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('should create and show the page title', () => {
    loadPolicy();
    expect(component).toBeTruthy();
    expect(text()).toContain('Sharing');
  });

  // US2 Scenario: Given no policy has been configured, Then the default is 30 days, the minimum is 1 day and the maximum is 90 days.
  describe('Scenario: no policy has been configured', () => {
    it('shows 30 / 1 / 90 when the API returns the unset defaults', () => {
      loadPolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
      expect(component.loading).toBeFalse();
      expect(component.form.getRawValue()).toEqual({ defaultExpiryDays: 30, minExpiryDays: 1, maxExpiryDays: 90 });
      expect(query<HTMLInputElement>('[data-testid="default-expiry"]')!.value).toBe('30');
      expect(query<HTMLInputElement>('[data-testid="min-expiry"]')!.value).toBe('1');
      expect(query<HTMLInputElement>('[data-testid="max-expiry"]')!.value).toBe('90');
    });

    it('falls back to 30 / 1 / 90 when the API omits values', () => {
      loadPolicy({});
      expect(component.form.getRawValue()).toEqual({ defaultExpiryDays: 30, minExpiryDays: 1, maxExpiryDays: 90 });
    });

    it('loads an existing configured policy', () => {
      loadPolicy({ default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60 });
      expect(component.form.getRawValue()).toEqual({ defaultExpiryDays: 14, minExpiryDays: 7, maxExpiryDays: 60 });
      expect(saveButton().disabled).toBeTrue();
    });
  });

  // US2 Scenario: Given I am a workspace owner, When I set the default to D days,
  // Then D must be between the current min and max (and never above 90), or the change is rejected with 422.
  describe('Scenario: workspace owner sets the default and bounds', () => {
    beforeEach(() => loadPolicy());

    it('saves a valid policy with PUT and the contract field names', () => {
      setValues({ defaultExpiryDays: 14, minExpiryDays: 7, maxExpiryDays: 60 });
      expect(saveButton().disabled).toBeFalse();
      saveButton().click();

      const req = http.expectOne({ method: 'PUT', url: POLICY_URL });
      expect(req.request.body).toEqual({ default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60 });
      req.flush({ default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60 });
      fixture.detectChanges();

      expect(component.saving).toBeFalse();
      expect(component.serverError).toBeNull();
      expect(component.form.pristine).toBeTrue();
      expect(component.form.getRawValue()).toEqual({ defaultExpiryDays: 14, minExpiryDays: 7, maxExpiryDays: 60 });
    });

    it('accepts the boundary values 1 and 90', () => {
      setValues({ defaultExpiryDays: 1, minExpiryDays: 1, maxExpiryDays: 90 });
      expect(component.form.valid).toBeTrue();
      setValues({ defaultExpiryDays: 90, minExpiryDays: 90, maxExpiryDays: 90 });
      expect(component.form.valid).toBeTrue();
    });

    it('rejects values above 90 client-side and does not call the API', () => {
      setValues({ maxExpiryDays: 91 });
      expect(component.form.invalid).toBeTrue();
      expect(text()).toContain('Must be between 1 and 90 days');
      expect(saveButton().disabled).toBeTrue();
      component.save();
      http.expectNone({ method: 'PUT', url: POLICY_URL });
    });

    it('rejects values below 1 client-side', () => {
      setValues({ minExpiryDays: 0 });
      expect(component.form.controls.minExpiryDays.hasError('min')).toBeTrue();
      expect(text()).toContain('Must be between 1 and 90 days');
      expect(saveButton().disabled).toBeTrue();
    });

    it('rejects empty and fractional values client-side', () => {
      setValues({ defaultExpiryDays: null });
      expect(text()).toContain('Enter a number of days');
      setValues({ defaultExpiryDays: 7.5 });
      expect(text()).toContain('Use whole days');
      expect(saveButton().disabled).toBeTrue();
    });

    it('rejects a minimum greater than the maximum', () => {
      setValues({ defaultExpiryDays: 30, minExpiryDays: 40, maxExpiryDays: 20 });
      expect(component.form.hasError('minAboveMax')).toBeTrue();
      expect(text()).toContain('Minimum expiry cannot be greater than maximum expiry.');
      expect(saveButton().disabled).toBeTrue();
    });

    it('rejects a default outside [min, max]', () => {
      setValues({ defaultExpiryDays: 5, minExpiryDays: 7, maxExpiryDays: 60 });
      expect(component.form.hasError('defaultOutOfRange')).toBeTrue();
      expect(text()).toContain('Default expiry must be between the minimum (7) and maximum (60) days.');
      setValues({ defaultExpiryDays: 61 });
      expect(component.form.hasError('defaultOutOfRange')).toBeTrue();
      expect(saveButton().disabled).toBeTrue();
    });

    it('shows the server 422 message when the API rejects the change', () => {
      setValues({ defaultExpiryDays: 14, minExpiryDays: 7, maxExpiryDays: 60 });
      saveButton().click();
      http.expectOne({ method: 'PUT', url: POLICY_URL }).flush(
        { error: 'default_expiry_days must be between min_expiry_days and max_expiry_days' },
        { status: 422, statusText: 'Unprocessable Entity' },
      );
      fixture.detectChanges();
      expect(component.saving).toBeFalse();
      expect(query('.server-error')!.textContent).toContain(
        'default_expiry_days must be between min_expiry_days and max_expiry_days');
      expect(component.form.dirty).toBeTrue();
    });

    it('shows a Rails-style errors hash from a 422', () => {
      setValues({ defaultExpiryDays: 14 });
      saveButton().click();
      http.expectOne({ method: 'PUT', url: POLICY_URL }).flush(
        { errors: { max_expiry_days: ['must be less than or equal to 90'] } },
        { status: 422, statusText: 'Unprocessable Entity' },
      );
      fixture.detectChanges();
      expect(query('.server-error')!.textContent).toContain('max expiry days must be less than or equal to 90');
    });

    it('reset restores the last saved values', () => {
      setValues({ defaultExpiryDays: 10 });
      component.reset();
      expect(component.form.getRawValue().defaultExpiryDays).toBe(30);
      expect(component.form.pristine).toBeTrue();
    });
  });

  // US2 Scenario: Given I change the default or bounds, Then only links created afterwards use the new values.
  describe('Scenario: changes apply only to new links', () => {
    it('states on the page that changes apply only to new links', () => {
      loadPolicy();
      const note = query('.new-links-note')!;
      expect(note.textContent).toContain('Changes apply only to new folder share links.');
      expect(note.textContent).toContain('Existing links keep the expiry date they were created with.');
    });
  });

  // US2 Scenario: Given I am not a workspace owner, When I try to change the policy, Then I get 403.
  describe('Scenario: caller is not a workspace owner', () => {
    it('shows an owner-only message when saving returns 403', () => {
      loadPolicy();
      setValues({ defaultExpiryDays: 14 });
      saveButton().click();
      http.expectOne({ method: 'PUT', url: POLICY_URL }).flush(
        { error: 'forbidden' }, { status: 403, statusText: 'Forbidden' });
      fixture.detectChanges();
      expect(query('.server-error')!.textContent).toContain('Only workspace owners can change the sharing policy.');
    });
  });

  describe('loading errors', () => {
    it('shows an error with a retry when the policy cannot be loaded', () => {
      fixture.detectChanges();
      http.expectOne(POLICY_URL).flush(null, { status: 503, statusText: 'Service Unavailable' });
      fixture.detectChanges();
      expect(query('.load-error')!.textContent).toContain('Could not load the sharing policy.');
      expect(query('form')).toBeNull();

      component.load();
      http.expectOne(POLICY_URL).flush({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
      fixture.detectChanges();
      expect(query('form')).toBeTruthy();
    });
  });
});
