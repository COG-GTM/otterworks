import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of, throwError } from 'rxjs';
import { WorkspaceSettingsComponent } from './workspace-settings.component';
import { AdminApiService } from '../../core/services/admin-api.service';
import { WorkspaceSharePolicy } from '../../core/models/share-policy.model';

// OTW-49 (parent OTW-41): workspace sharing settings form.
function makePolicy(overrides: Partial<WorkspaceSharePolicy> = {}): WorkspaceSharePolicy {
  return {
    workspaceId: 'default',
    defaultDays: 30,
    maxDays: 90,
    updatedAt: null,
    updatedBy: null,
    ...overrides,
  };
}

describe('WorkspaceSettingsComponent (OTW-49)', () => {
  let component: WorkspaceSettingsComponent;
  let fixture: ComponentFixture<WorkspaceSettingsComponent>;
  let apiSpy: jasmine.SpyObj<AdminApiService>;

  const el = () => fixture.nativeElement as HTMLElement;

  function setValues(defaultDays: number | null, maxDays: number | null): void {
    component.form.setValue({ defaultDays, maxDays });
    component.form.markAsDirty();
    component.form.markAllAsTouched();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    apiSpy = jasmine.createSpyObj('AdminApiService', ['getWorkspaceSharePolicy', 'updateWorkspaceSharePolicy']);
    apiSpy.getWorkspaceSharePolicy.and.returnValue(of(makePolicy()));

    await TestBed.configureTestingModule({
      imports: [WorkspaceSettingsComponent, NoopAnimationsModule],
      providers: [{ provide: AdminApiService, useValue: apiSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(WorkspaceSettingsComponent);
    component = fixture.componentInstance;
  });

  describe('AC1 - Given a workspace owner opens workspace settings', () => {
    it('When the page loads, Then it fetches GET share-policy and shows the 30/90 defaults of a new workspace', () => {
      fixture.detectChanges();

      expect(apiSpy.getWorkspaceSharePolicy).toHaveBeenCalledTimes(1);
      expect(component.loading).toBeFalse();
      expect(component.form.value).toEqual({ defaultDays: 30, maxDays: 90 });
      const current = el().querySelector('[data-testid="current-policy"]')!.textContent!;
      expect(current).toContain('30 days');
      expect(current).toContain('90 days');
    });

    it('When the workspace already has a custom policy, Then the form shows the stored values', () => {
      apiSpy.getWorkspaceSharePolicy.and.returnValue(of(makePolicy({
        defaultDays: 7, maxDays: 14, updatedAt: '2026-11-01T10:00:00Z', updatedBy: 'u-1',
      })));
      fixture.detectChanges();

      expect(component.form.value).toEqual({ defaultDays: 7, maxDays: 14 });
      expect(el().querySelector('[data-testid="current-policy"]')!.textContent).toContain('7 days');
      expect(el().querySelector('.updated-at')).toBeTruthy();
    });

    it('When the policy is 1/1, Then the current policy uses the singular "day"', () => {
      apiSpy.getWorkspaceSharePolicy.and.returnValue(of(makePolicy({ defaultDays: 1, maxDays: 1 })));
      fixture.detectChanges();

      const current = el().querySelector('[data-testid="current-policy"]')!.textContent!;
      expect(current).toContain('1 day by default');
      expect(current).not.toContain('1 days');
    });

    it('When loading fails, Then an error with a retry is shown instead of the form', () => {
      apiSpy.getWorkspaceSharePolicy.and.returnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
      fixture.detectChanges();

      expect(component.loadError).toBe('Could not load the workspace sharing policy.');
      expect(el().querySelector('form')).toBeNull();
      expect(el().querySelector('.load-error')).toBeTruthy();
    });
  });

  describe('AC2 - Given they save a default from 1 to 90 days, no higher than the maximum', () => {
    beforeEach(() => fixture.detectChanges());

    for (const [defaultDays, maxDays] of [[1, 90], [45, 60], [90, 90]]) {
      it(`When they save default=${defaultDays} max=${maxDays}, Then it is sent via PUT share-policy`, () => {
        apiSpy.updateWorkspaceSharePolicy.and.returnValue(of(makePolicy({ defaultDays, maxDays })));
        setValues(defaultDays, maxDays);

        component.save();

        expect(apiSpy.updateWorkspaceSharePolicy).toHaveBeenCalledOnceWith({ defaultDays, maxDays });
        expect(component.saving).toBeFalse();
        expect(component.saveError).toBe('');
        expect(component.policy).toEqual(jasmine.objectContaining({ defaultDays, maxDays }));
        expect(component.form.pristine).toBeTrue();
      });
    }

    it('When the Save button is clicked, Then the form submits the values', () => {
      apiSpy.updateWorkspaceSharePolicy.and.returnValue(of(makePolicy({ defaultDays: 14 })));
      setValues(14, 90);

      const submit = el().querySelector('button[type="submit"]') as HTMLButtonElement;
      expect(submit.disabled).toBeFalse();
      submit.click();

      expect(apiSpy.updateWorkspaceSharePolicy).toHaveBeenCalledOnceWith({ defaultDays: 14, maxDays: 90 });
    });
  });

  describe('AC3 - Given an out-of-range value', () => {
    beforeEach(() => fixture.detectChanges());

    const outOfRange: Array<[string, number | null, number | null, 'defaultDays' | 'maxDays']> = [
      ['default of 0', 0, 90, 'defaultDays'],
      ['default of 91', 91, 90, 'defaultDays'],
      ['maximum of 91', 30, 91, 'maxDays'],
      ['maximum of 0', 30, 0, 'maxDays'],
      ['empty default', null, 90, 'defaultDays'],
    ];

    for (const [label, defaultDays, maxDays, field] of outOfRange) {
      it(`When they enter a ${label}, Then the form shows a validation error and does not call the API`, () => {
        setValues(defaultDays, maxDays);

        expect(component.form.controls[field].invalid).toBeTrue();
        expect(el().querySelector('mat-error')).toBeTruthy();
        expect((el().querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBeTrue();
        component.save();
        expect(apiSpy.updateWorkspaceSharePolicy).not.toHaveBeenCalled();
      });
    }

    it('When the value is not a whole number, Then the form shows a validation error', () => {
      setValues(10.5, 90);

      expect(component.fieldError('defaultDays')).toBe('Use a whole number of days.');
      component.save();
      expect(apiSpy.updateWorkspaceSharePolicy).not.toHaveBeenCalled();
    });

    it('When the default is higher than the maximum, Then the form shows a validation error', () => {
      setValues(60, 30);

      expect(component.form.hasError('defaultAboveMax')).toBeTrue();
      expect(el().querySelector('[data-testid="default-above-max"]')).toBeTruthy();
      component.save();
      expect(apiSpy.updateWorkspaceSharePolicy).not.toHaveBeenCalled();
    });

    it('When the API responds 422, Then the server message is shown to the user', () => {
      apiSpy.updateWorkspaceSharePolicy.and.returnValue(throwError(() => new HttpErrorResponse({
        status: 422,
        error: { detail: 'default_days must be <= max_days' },
      })));
      setValues(20, 30);

      component.save();
      fixture.detectChanges();

      expect(component.saving).toBeFalse();
      const banner = el().querySelector('[data-testid="save-error"]')!.textContent!;
      expect(banner).toContain('The server rejected these values');
      expect(banner).toContain('default_days must be <= max_days');
    });

    it('When the API responds 422 with FastAPI validation details, Then each message is shown', () => {
      apiSpy.updateWorkspaceSharePolicy.and.returnValue(throwError(() => new HttpErrorResponse({
        status: 422,
        error: { detail: [{ msg: 'Input should be less than or equal to 90' }] },
      })));
      setValues(20, 30);

      component.save();

      expect(component.saveError).toContain('Input should be less than or equal to 90');
    });

    it('When the API responds 403 for a non-owner, Then a permission error is shown', () => {
      apiSpy.updateWorkspaceSharePolicy.and.returnValue(throwError(() => new HttpErrorResponse({ status: 403 })));
      setValues(20, 30);

      component.save();

      expect(component.saveError).toBe('Only workspace owners can change sharing settings.');
    });
  });

  describe('AC4 - The form notes that changes apply only to links created afterwards', () => {
    it('When the form is shown, Then the note about links created afterwards is visible', () => {
      fixture.detectChanges();

      const note = el().querySelector('[data-testid="apply-note"]')!.textContent!;
      expect(note).toContain('Changes apply only to links created afterwards');
    });
  });

  it('Reset restores the last loaded policy and clears save errors', () => {
    fixture.detectChanges();
    setValues(5, 10);
    component.saveError = 'boom';

    component.reset();

    expect(component.form.value).toEqual({ defaultDays: 30, maxDays: 90 });
    expect(component.saveError).toBe('');
  });
});
