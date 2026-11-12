import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { IncidentsComponent } from './incidents.component';
import { AdminApiService } from '../../core/services/admin-api.service';
import { Incident } from '../../core/models/incident.model';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { OverlayModule } from '@angular/cdk/overlay';

function makeIncident(overrides: Partial<Incident> = {}): Incident {
  return {
    id: 'inc-001',
    title: 'Test incident',
    description: 'A test',
    severity: 'high',
    status: 'investigating',
    affectedService: 'search-service',
    devinSessionId: null,
    devinSessionUrl: null,
    devinSessionStatus: null,
    reporterId: null,
    resolvedAt: null,
    closedAt: null,
    active: true,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('IncidentsComponent', () => {
  let component: IncidentsComponent;
  let fixture: ComponentFixture<IncidentsComponent>;
  let apiSpy: jasmine.SpyObj<AdminApiService>;
  let dialog: MatDialog;

  beforeEach(async () => {
    apiSpy = jasmine.createSpyObj('AdminApiService', [
      'getIncidents', 'createIncident', 'triggerDevinSession',
      'updateIncidentStatus', 'deleteIncident',
      'triggerChaos', 'resetChaos', 'getAutoInvestigate', 'setAutoInvestigate',
    ]);

    apiSpy.getIncidents.and.returnValue(of([]));
    apiSpy.getAutoInvestigate.and.returnValue(of({ enabled: true }));

    await TestBed.configureTestingModule({
      imports: [
        IncidentsComponent,
        HttpClientTestingModule,
        NoopAnimationsModule,
        MatDialogModule,
        OverlayModule,
      ],
      providers: [
        { provide: AdminApiService, useValue: apiSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(IncidentsComponent);
    component = fixture.componentInstance;
    dialog = TestBed.inject(MatDialog);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start with loading state', () => {
    expect(component.loading).toBeTrue();
  });

  it('should default showClosed to false', () => {
    expect(component.showClosed).toBeFalse();
  });

  describe('filteredIncidents', () => {
    const openInc = makeIncident({ id: 'open-1', status: 'open', active: true });
    const investigatingInc = makeIncident({ id: 'inv-1', status: 'investigating', active: true });
    const resolvedInc = makeIncident({ id: 'res-1', status: 'resolved', active: false });
    const closedInc = makeIncident({ id: 'cls-1', status: 'closed', active: false });

    beforeEach(() => {
      component.incidents = [openInc, investigatingInc, resolvedInc, closedInc];
    });

    it('should exclude closed incidents by default', () => {
      component.showClosed = false;
      component.filterStatus = '';
      const filtered = component.filteredIncidents;
      expect(filtered.length).toBe(3);
      expect(filtered.find(i => i.status === 'closed')).toBeUndefined();
    });

    it('should include closed incidents when showClosed is true', () => {
      component.showClosed = true;
      component.filterStatus = '';
      const filtered = component.filteredIncidents;
      expect(filtered.length).toBe(4);
      expect(filtered.find(i => i.status === 'closed')).toBeDefined();
    });

    it('should filter by active status', () => {
      component.showClosed = true;
      component.filterStatus = 'active';
      const filtered = component.filteredIncidents;
      expect(filtered.every(i => i.active)).toBeTrue();
    });
  });

  describe('closedCount', () => {
    it('should return the count of closed incidents', () => {
      component.incidents = [
        makeIncident({ id: '1', status: 'investigating' }),
        makeIncident({ id: '2', status: 'closed' }),
        makeIncident({ id: '3', status: 'closed' }),
      ];
      expect(component.closedCount).toBe(2);
    });

    it('should return 0 when no closed incidents', () => {
      component.incidents = [makeIncident({ id: '1', status: 'open' })];
      expect(component.closedCount).toBe(0);
    });
  });

  function spyDialog(confirmed: boolean): void {
    spyOn((component as any).dialog, 'open').and.returnValue({
      afterClosed: () => of(confirmed),
    } as any);
  }

  describe('resolveIncident', () => {
    it('should call updateIncidentStatus with resolved', () => {
      const incident = makeIncident({ status: 'investigating' });
      const resolved = makeIncident({ status: 'resolved', resolvedAt: '2026-01-01T00:00:00Z' });
      spyDialog(true);
      apiSpy.updateIncidentStatus.and.returnValue(of(resolved));

      component.incidents = [incident];
      component.resolveIncident(incident);

      expect(apiSpy.updateIncidentStatus).toHaveBeenCalledWith('inc-001', 'resolved');
    });

    it('should not call API when dialog is dismissed', () => {
      const incident = makeIncident();
      spyDialog(false);

      component.resolveIncident(incident);

      expect(apiSpy.updateIncidentStatus).not.toHaveBeenCalled();
    });
  });

  describe('closeIncident', () => {
    it('should call updateIncidentStatus with closed', () => {
      const incident = makeIncident({ status: 'resolved' });
      const closed = makeIncident({ status: 'closed', closedAt: '2026-01-01T00:00:00Z' });
      spyDialog(true);
      apiSpy.updateIncidentStatus.and.returnValue(of(closed));

      component.incidents = [incident];
      component.closeIncident(incident);

      expect(apiSpy.updateIncidentStatus).toHaveBeenCalledWith('inc-001', 'closed');
    });
  });

  describe('deleteIncident', () => {
    it('should call deleteIncident and remove from list', () => {
      const incident = makeIncident();
      spyDialog(true);
      apiSpy.deleteIncident.and.returnValue(of(void 0));

      component.incidents = [incident];
      component.deleteIncident(incident);

      expect(apiSpy.deleteIncident).toHaveBeenCalledWith('inc-001');
      expect(component.incidents.length).toBe(0);
    });

    it('should not call API when dialog is dismissed', () => {
      const incident = makeIncident();
      spyDialog(false);

      component.deleteIncident(incident);

      expect(apiSpy.deleteIncident).not.toHaveBeenCalled();
    });
  });

  describe('chaos controls', () => {
    const secretRequired = () => throwError(() => new HttpErrorResponse({
      status: 403, error: { code: 'chaos_secret_required' },
    }));

    beforeEach(() => sessionStorage.removeItem('ow_admin_chaos_secret'));
    afterEach(() => sessionStorage.removeItem('ow_admin_chaos_secret'));

    it('prompts for the chaos secret and sends it with the trigger', () => {
      spyOn(window, 'prompt').and.returnValue('s3cret');
      apiSpy.triggerChaos.and.returnValue(of({ status: 'chaos_active', key: 'k', expires_in: 600 }));

      component.triggerChaos('file-service', 'upload_s3_error');

      expect(apiSpy.triggerChaos).toHaveBeenCalledWith('file-service', 'upload_s3_error', 's3cret');
      expect(component.chaosState['file-service']).toBeTrue();
      expect(sessionStorage.getItem('ow_admin_chaos_secret')).toBe('s3cret');
    });

    it('does not call the API when the prompt is cancelled', () => {
      spyOn(window, 'prompt').and.returnValue(null);

      component.triggerChaos('file-service', 'upload_s3_error');

      expect(apiSpy.triggerChaos).not.toHaveBeenCalled();
    });

    it('re-prompts once when the stored secret is rejected', () => {
      sessionStorage.setItem('ow_admin_chaos_secret', 'stale');
      spyOn(window, 'prompt').and.returnValue('fresh');
      apiSpy.resetChaos.and.returnValues(secretRequired(), of({ status: 'reset', cleared: [] }));

      component.resetAllChaos();

      expect(apiSpy.resetChaos.calls.allArgs()).toEqual([['stale'], ['fresh']]);
      expect(sessionStorage.getItem('ow_admin_chaos_secret')).toBe('fresh');
    });

    it('stops after a second rejection and clears the stored secret', () => {
      spyOn(window, 'prompt').and.returnValue('wrong');
      apiSpy.triggerChaos.and.returnValue(secretRequired());

      component.triggerChaos('file-service', 'upload_s3_error');

      expect(apiSpy.triggerChaos).toHaveBeenCalledTimes(2);
      expect(sessionStorage.getItem('ow_admin_chaos_secret')).toBeNull();
      expect(component.chaosState['file-service']).toBeFalsy();
    });
  });
});
