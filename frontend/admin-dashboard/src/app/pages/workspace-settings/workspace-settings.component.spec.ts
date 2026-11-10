import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject, of, throwError } from 'rxjs';
import { WorkspaceSettingsComponent } from './workspace-settings.component';
import { SharePolicyService } from '../../core/services/share-policy.service';
import { SharePolicy } from '../../core/models/share-policy.model';

function makePolicy(overrides: Partial<SharePolicy> = {}): SharePolicy {
  return {
    workspaceId: 'default', defaultExpiryDays: 7, minExpiryDays: 1, maxExpiryDays: 30,
    updatedBy: null, updatedAt: null, ...overrides,
  };
}

describe('WorkspaceSettingsComponent (OTW-81, OTW-74 US1-2 / AC1-AC3 / AC7)', () => {
  let fixture: ComponentFixture<WorkspaceSettingsComponent>;
  let component: WorkspaceSettingsComponent;
  let api: jasmine.SpyObj<SharePolicyService>;

  const el = () => fixture.nativeElement as HTMLElement;
  const q = (sel: string) => el().querySelector(sel) as HTMLElement | null;
  const saveButton = () => q('[data-testid="save-policy"]') as HTMLButtonElement;
  const setField = (key: string, value: number | string) => {
    const input = q(`[data-testid="${key}"]`) as HTMLInputElement;
    input.value = String(value);
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  };

  async function setup(getResult = of(makePolicy())) {
    api = jasmine.createSpyObj('SharePolicyService', ['getPolicy', 'updatePolicy']);
    api.getPolicy.and.returnValue(getResult);
    await TestBed.configureTestingModule({
      imports: [WorkspaceSettingsComponent, NoopAnimationsModule],
      providers: [{ provide: SharePolicyService, useValue: api }],
    }).compileComponents();
    fixture = TestBed.createComponent(WorkspaceSettingsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  describe('loaded policy', () => {
    beforeEach(async () => setup());

    it('US1/AC1: shows the current workspace default expiry and bounds', () => {
      expect(api.getPolicy).toHaveBeenCalled();
      expect((q('[data-testid="defaultExpiryDays"]') as HTMLInputElement).value).toBe('7');
      expect((q('[data-testid="minExpiryDays"]') as HTMLInputElement).value).toBe('1');
      expect((q('[data-testid="maxExpiryDays"]') as HTMLInputElement).value).toBe('30');
      expect(el().textContent).toContain('Using built-in defaults');
      expect(q('[data-testid="policy-preview"]')!.textContent).toContain('7');
    });

    it('AC7: tells the owner changes only apply to links created afterwards', () => {
      const note = q('[role="note"]')!.textContent!;
      expect(note).toContain('apply only to share links created after you save');
      expect(note).toContain('never expired retroactively');
    });

    it('keeps Save disabled until something changes', () => {
      expect(saveButton().disabled).toBeTrue();
      setField('defaultExpiryDays', 14);
      expect(saveButton().disabled).toBeFalse();
    });

    it('US1/AC1: saving a new default sends it to the API and shows the saved policy', () => {
      api.updatePolicy.and.returnValue(of(makePolicy({
        defaultExpiryDays: 14, updatedBy: 'owner-1', updatedAt: '2026-11-10T17:00:00Z',
      })));
      setField('defaultExpiryDays', 14);
      saveButton().click();
      fixture.detectChanges();

      expect(api.updatePolicy).toHaveBeenCalledOnceWith({ defaultExpiryDays: 14, minExpiryDays: 1, maxExpiryDays: 30 });
      expect(el().textContent).toContain('by owner-1');
      expect(component.form.pristine).toBeTrue();
    });

    it('US2/AC2: saving min/max bounds 1..30 (so a 14-day override is allowed) sends them to the API', () => {
      api.updatePolicy.and.returnValue(of(makePolicy({ minExpiryDays: 2, maxExpiryDays: 30 })));
      setField('minExpiryDays', 2);
      setField('maxExpiryDays', 30);
      saveButton().click();
      expect(api.updatePolicy).toHaveBeenCalledOnceWith({ defaultExpiryDays: 7, minExpiryDays: 2, maxExpiryDays: 30 });
    });

    it('AC3: maximum above 365 is rejected client-side and never sent', () => {
      setField('maxExpiryDays', 400);
      expect(el().textContent).toContain('Cannot exceed 365 days');
      expect(saveButton().disabled).toBeTrue();
      component.save();
      expect(api.updatePolicy).not.toHaveBeenCalled();
    });

    it('AC3: minimum below 1 is rejected client-side', () => {
      setField('minExpiryDays', 0);
      expect(el().textContent).toContain('Must be at least 1 day');
      expect(saveButton().disabled).toBeTrue();
    });

    it('AC3: minimum greater than default is rejected client-side', () => {
      setField('minExpiryDays', 10);
      expect(q('[data-testid="min-above-default"]')).toBeTruthy();
      expect(saveButton().disabled).toBeTrue();
    });

    it('AC3: default greater than maximum (e.g. 90 with max 30) is rejected client-side', () => {
      setField('defaultExpiryDays', 90);
      expect(q('[data-testid="default-above-max"]')).toBeTruthy();
      expect(saveButton().disabled).toBeTrue();
    });

    it('rejects fractional and empty values', () => {
      setField('defaultExpiryDays', '2.5');
      expect(el().textContent).toContain('Enter a whole number of days');
      setField('defaultExpiryDays', '');
      expect(el().textContent).toContain('Required');
      expect(saveButton().disabled).toBeTrue();
    });

    it('AC3: shows the server 422 detail and keeps the unsaved values', () => {
      api.updatePolicy.and.returnValue(throwError(() => new HttpErrorResponse({
        status: 422, error: { detail: 'default_expiry_days must be between min_expiry_days (1) and max_expiry_days (30)' },
      })));
      setField('defaultExpiryDays', 20);
      saveButton().click();
      fixture.detectChanges();

      expect(q('[data-testid="save-error"]')!.textContent).toContain('must be between min_expiry_days (1) and max_expiry_days (30)');
      expect(component.form.value.defaultExpiryDays).toBe(20);
      expect(component.policy!.defaultExpiryDays).toBe(7);
    });

    it('explains a 403 as workspace-owner only', () => {
      api.updatePolicy.and.returnValue(throwError(() => new HttpErrorResponse({ status: 403 })));
      setField('defaultExpiryDays', 10);
      saveButton().click();
      fixture.detectChanges();
      expect(q('[data-testid="save-error"]')!.textContent).toContain('Only a workspace owner');
    });

    it('disables Save while a request is in flight', () => {
      const pending = new Subject<SharePolicy>();
      api.updatePolicy.and.returnValue(pending.asObservable());
      setField('defaultExpiryDays', 10);
      saveButton().click();
      fixture.detectChanges();
      expect(saveButton().disabled).toBeTrue();
      pending.next(makePolicy({ defaultExpiryDays: 10 }));
      fixture.detectChanges();
      expect(component.saving).toBeFalse();
    });

    it('Reset restores the saved values', () => {
      setField('defaultExpiryDays', 12);
      component.reset();
      fixture.detectChanges();
      expect(component.form.value.defaultExpiryDays).toBe(7);
      expect(component.form.pristine).toBeTrue();
    });
  });

  it('shows a load error with Retry when the policy cannot be fetched', async () => {
    await setup(throwError(() => new HttpErrorResponse({ status: 500 })));
    expect(el().textContent).toContain('Could not load the share-link expiry policy');
    api.getPolicy.and.returnValue(of(makePolicy()));
    (q('.retry-btn') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect((q('[data-testid="defaultExpiryDays"]') as HTMLInputElement).value).toBe('7');
  });
});
