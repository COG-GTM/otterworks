import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of, throwError } from 'rxjs';
import { SharingComponent, formatDuration, toDurationField, toSeconds } from './sharing.component';
import { AdminApiService } from '../../core/services/admin-api.service';
import { DEFAULT_SHARE_POLICY } from '../../core/services/mock-data/share-policy.mock';
import { SharePolicy } from '../../core/models/share-policy.model';

const DAY = 86400;
const HOUR = 3600;

describe('SharingComponent', () => {
  let fixture: ComponentFixture<SharingComponent>;
  let component: SharingComponent;
  let apiSpy: jasmine.SpyObj<AdminApiService>;

  const el = (sel: string): HTMLElement | null => fixture.nativeElement.querySelector(`[data-test="${sel}"]`);
  const input = (key: string): HTMLInputElement => el(`${key}-value`) as HTMLInputElement;

  async function render(policy: SharePolicy = { ...DEFAULT_SHARE_POLICY }) {
    apiSpy.getSharePolicy.and.returnValue(of(policy));
    fixture = TestBed.createComponent(SharingComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function setForm(def: [number, 'hours' | 'days'], min: [number, 'hours' | 'days'], max: [number, 'hours' | 'days']) {
    component.form!.defaultExpiry = { value: def[0], unit: def[1] };
    component.form!.minExpiry = { value: min[0], unit: min[1] };
    component.form!.maxExpiry = { value: max[0], unit: max[1] };
    component.onEdit();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    apiSpy = jasmine.createSpyObj('AdminApiService', ['getSharePolicy', 'updateSharePolicy']);
    await TestBed.configureTestingModule({
      imports: [SharingComponent, NoopAnimationsModule],
      providers: [{ provide: AdminApiService, useValue: apiSpy }],
    }).compileComponents();
  });

  describe('load', () => {
    it('Given no saved policy, When the page loads, Then it shows 30 days / 1 hour / 365 days / never-expires off', async () => {
      await render();
      expect(apiSpy.getSharePolicy).toHaveBeenCalledTimes(1);
      expect(component.form!.defaultExpiry).toEqual({ value: 30, unit: 'days' });
      expect(component.form!.minExpiry).toEqual({ value: 1, unit: 'hours' });
      expect(component.form!.maxExpiry).toEqual({ value: 365, unit: 'days' });
      expect(component.form!.allowNever).toBeFalse();
      expect(input('defaultExpiry').value).toBe('30');
      expect(input('minExpiry').value).toBe('1');
      expect(input('maxExpiry').value).toBe('365');
      expect(el('allow-never')!.textContent).toContain('Off');
      expect(el('summary')!.textContent).toContain('30 days');
      expect(el('summary')!.textContent).toContain('1 hour and');
      expect((el('save') as HTMLButtonElement).disabled).toBeTrue();
    });

    it('shows an error banner when the policy cannot be loaded', async () => {
      apiSpy.getSharePolicy.and.returnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
      fixture = TestBed.createComponent(SharingComponent);
      component = fixture.componentInstance;
      fixture.detectChanges();
      expect(component.loading).toBeFalse();
      expect(el('load-error')!.textContent).toContain('Could not load sharing settings');
    });
  });

  describe('save', () => {
    it('Given a workspace owner, When they save valid values, Then they are persisted and a confirmation is shown', async () => {
      await render();
      const saved: SharePolicy = {
        ...DEFAULT_SHARE_POLICY,
        defaultExpirySeconds: 7 * DAY, minExpirySeconds: HOUR, maxExpirySeconds: 90 * DAY,
        updatedBy: 'owner-1', updatedAt: '2026-11-10T00:00:00Z',
      };
      apiSpy.updateSharePolicy.and.returnValue(of(saved));

      setForm([7, 'days'], [1, 'hours'], [90, 'days']);
      expect((el('save') as HTMLButtonElement).disabled).toBeFalse();
      (el('save') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(apiSpy.updateSharePolicy).toHaveBeenCalledOnceWith({
        defaultExpirySeconds: 7 * DAY, minExpirySeconds: HOUR, maxExpirySeconds: 90 * DAY, allowNever: false,
      });
      expect(component.policy).toEqual(saved);
      expect(component.dirty).toBeFalse();
      expect(el('saved-message')!.textContent).toContain('Sharing settings saved');
      expect(el('last-updated')!.textContent).toContain('owner-1');
    });

    it('sends allow_never when the toggle is turned on', async () => {
      await render();
      apiSpy.updateSharePolicy.and.returnValue(of({ ...DEFAULT_SHARE_POLICY, allowNever: true }));
      component.form!.allowNever = true;
      component.onEdit();
      component.save();
      expect(apiSpy.updateSharePolicy.calls.mostRecent().args[0].allowNever).toBeTrue();
    });

    it('shows a workspace-owner message on 403 and keeps the saved policy', async () => {
      await render();
      apiSpy.updateSharePolicy.and.returnValue(throwError(() => new HttpErrorResponse({ status: 403 })));
      setForm([7, 'days'], [1, 'hours'], [90, 'days']);
      component.save();
      fixture.detectChanges();
      expect(el('server-error')!.textContent).toContain('Only workspace owners');
      expect(component.policy!.maxExpirySeconds).toBe(365 * DAY);
    });
  });

  describe('validation', () => {
    const cases: { name: string; def: [number, 'hours' | 'days']; min: [number, 'hours' | 'days']; max: [number, 'hours' | 'days']; msg: string }[] = [
      { name: 'default above max', def: [100, 'days'], min: [1, 'hours'], max: [90, 'days'], msg: 'Default expiry must be between' },
      { name: 'default below min', def: [2, 'hours'], min: [1, 'days'], max: [90, 'days'], msg: 'Default expiry must be between' },
      { name: 'min greater than max', def: [5, 'days'], min: [10, 'days'], max: [5, 'days'], msg: 'Minimum expiry cannot be greater' },
      { name: 'max above 365 days', def: [30, 'days'], min: [1, 'hours'], max: [400, 'days'], msg: 'cannot be more than 365 days' },
    ];

    cases.forEach(c => {
      it(`Given ${c.name}, When saving, Then client-side validation blocks the save and nothing changes`, async () => {
        await render();
        setForm(c.def, c.min, c.max);
        expect(el('client-errors')!.textContent).toContain(c.msg);
        expect((el('save') as HTMLButtonElement).disabled).toBeTrue();
        component.save();
        expect(apiSpy.updateSharePolicy).not.toHaveBeenCalled();
        expect(component.policy).toEqual(DEFAULT_SHARE_POLICY);
      });
    });

    it('rejects empty and non-positive values client-side', async () => {
      await render();
      setForm([0, 'days'], [1, 'hours'], [90, 'days']);
      expect(el('client-errors')!.textContent).toContain('positive whole numbers');
      component.form!.defaultExpiry.value = null;
      fixture.detectChanges();
      expect(component.clientErrors.length).toBeGreaterThan(0);
    });

    it('Given the API returns 422, When saving, Then the validation message is shown and nothing changes', async () => {
      await render();
      apiSpy.updateSharePolicy.and.returnValue(throwError(() => new HttpErrorResponse({
        status: 422, error: { detail: 'default_expiry_seconds must be between min and max' },
      })));
      setForm([7, 'days'], [1, 'hours'], [90, 'days']);
      (el('save') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(el('server-error')!.textContent).toContain('default_expiry_seconds must be between min and max');
      expect(el('saved-message')).toBeNull();
      expect(component.policy).toEqual(DEFAULT_SHARE_POLICY);
      expect(component.dirty).toBeTrue();
    });

    it('renders FastAPI field-error lists from a 422', async () => {
      await render();
      apiSpy.updateSharePolicy.and.returnValue(throwError(() => new HttpErrorResponse({
        status: 422, error: { detail: [{ loc: ['body', 'max_expiry_seconds'], msg: 'Input should be less than or equal to 31536000' }] },
      })));
      setForm([7, 'days'], [1, 'hours'], [90, 'days']);
      component.save();
      fixture.detectChanges();
      expect(el('server-error')!.textContent).toContain('less than or equal to 31536000');
    });

    it('Reset restores the last saved values', async () => {
      await render();
      setForm([100, 'days'], [1, 'hours'], [90, 'days']);
      (el('reset') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(component.form!.defaultExpiry).toEqual({ value: 30, unit: 'days' });
      expect(el('client-errors')).toBeNull();
    });
  });

  describe('duration helpers', () => {
    it('picks days when the value is a whole number of days, otherwise hours', () => {
      expect(toDurationField(2 * DAY)).toEqual({ value: 2, unit: 'days' });
      expect(toDurationField(36 * HOUR)).toEqual({ value: 36, unit: 'hours' });
      expect(toSeconds({ value: 12, unit: 'hours' })).toBe(12 * HOUR);
      expect(formatDuration(HOUR)).toBe('1 hour');
      expect(formatDuration(365 * DAY)).toBe('365 days');
    });
  });
});
