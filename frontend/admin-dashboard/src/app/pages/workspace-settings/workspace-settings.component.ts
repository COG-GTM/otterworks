import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, ValidatorFn, Validators,
} from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AdminApiService } from '../../core/services/admin-api.service';
import {
  SHARE_POLICY_DEFAULT_DAYS, SHARE_POLICY_MAX_DAYS, SHARE_POLICY_MIN_DAYS, WorkspaceSharePolicy,
} from '../../core/models/share-policy.model';

const defaultWithinMax: ValidatorFn = (group: AbstractControl): ValidationErrors | null => {
  const defaultDays = group.get('defaultDays')?.value;
  const maxDays = group.get('maxDays')?.value;
  if (defaultDays == null || maxDays == null || defaultDays === '' || maxDays === '') return null;
  return Number(defaultDays) > Number(maxDays) ? { defaultAboveMax: true } : null;
};

@Component({
  selector: 'app-workspace-settings',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, MatCardModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatIconModule, MatProgressSpinnerModule, MatSnackBarModule,
  ],
  template: `
    <div class="page-container">
      <h1 class="page-title">Workspace Settings</h1>

      <div *ngIf="loading" class="loading-container">
        <mat-spinner diameter="40"></mat-spinner>
      </div>

      <div *ngIf="!loading && loadError" class="error-banner load-error" role="alert">
        <mat-icon>error_outline</mat-icon>
        <span>{{ loadError }}</span>
        <button mat-button color="primary" (click)="load()">Retry</button>
      </div>

      <mat-card class="settings-card" *ngIf="!loading && !loadError">
        <mat-card-header>
          <mat-icon mat-card-avatar class="card-icon">link</mat-icon>
          <mat-card-title>Shared folder links</mat-card-title>
          <mat-card-subtitle>How long new read-only folder links stay valid</mat-card-subtitle>
        </mat-card-header>

        <mat-card-content>
          <p class="current-policy" data-testid="current-policy">
            Current policy: links expire after <strong>{{ policy?.defaultDays }} days</strong> by default,
            and can be set to at most <strong>{{ policy?.maxDays }} days</strong>.
            <span *ngIf="policy?.updatedAt" class="updated-at">
              Last updated {{ policy?.updatedAt | date:'medium' }}<span *ngIf="policy?.updatedBy"> by {{ policy?.updatedBy }}</span>.
            </span>
          </p>

          <form [formGroup]="form" (ngSubmit)="save()" novalidate>
            <div class="fields">
              <mat-form-field appearance="outline">
                <mat-label>Default link expiry (days)</mat-label>
                <input matInput type="number" formControlName="defaultDays" name="defaultDays"
                       [min]="minDays" [max]="maxAllowedDays" step="1" required>
                <mat-hint>Applied when a user does not choose an expiry.</mat-hint>
                <mat-error *ngIf="form.controls.defaultDays.invalid">{{ fieldError('defaultDays') }}</mat-error>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Maximum link expiry (days)</mat-label>
                <input matInput type="number" formControlName="maxDays" name="maxDays"
                       [min]="minDays" [max]="maxAllowedDays" step="1" required>
                <mat-hint>Users cannot pick an expiry longer than this.</mat-hint>
                <mat-error *ngIf="form.controls.maxDays.invalid">{{ fieldError('maxDays') }}</mat-error>
              </mat-form-field>
            </div>

            <div *ngIf="form.hasError('defaultAboveMax')" class="form-error" data-testid="default-above-max" role="alert">
              The default expiry cannot be longer than the maximum expiry.
            </div>

            <div class="apply-note" data-testid="apply-note">
              <mat-icon>info</mat-icon>
              <span>
                Changes apply only to links created afterwards. Existing links keep the expiry they were created with.
              </span>
            </div>

            <div *ngIf="saveError" class="error-banner" data-testid="save-error" role="alert">
              <mat-icon>error_outline</mat-icon>
              <span>{{ saveError }}</span>
            </div>

            <div class="actions">
              <button mat-stroked-button type="button" (click)="reset()" [disabled]="saving || form.pristine">Reset</button>
              <button mat-flat-button color="primary" type="submit" [disabled]="saving || form.invalid || form.pristine">
                {{ saving ? 'Saving…' : 'Save' }}
              </button>
            </div>
          </form>
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .page-container { padding: 0; }
    .page-title { font-size: 1.5rem; font-weight: 600; color: #333; margin-bottom: 24px; }
    .loading-container { display: flex; justify-content: center; padding: 60px; }
    .settings-card { max-width: 720px; }
    .card-icon { color: #1f3a5f; font-size: 32px; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; }
    .current-policy { margin: 16px 0 24px; color: #444; }
    .updated-at { display: block; font-size: 0.8rem; color: #888; margin-top: 4px; }
    .fields { display: flex; gap: 16px; flex-wrap: wrap; }
    .fields mat-form-field { flex: 1; min-width: 240px; }
    .form-error { color: #c62828; font-size: 0.85rem; margin: 4px 0 12px; }
    .apply-note {
      display: flex; align-items: flex-start; gap: 8px; margin: 16px 0;
      padding: 12px; border-radius: 4px; background: #e8f0fe; color: #1f3a5f; font-size: 0.9rem;
    }
    .error-banner {
      display: flex; align-items: center; gap: 8px; margin: 12px 0;
      padding: 12px; border-radius: 4px; background: #fdecea; color: #c62828; font-size: 0.9rem;
    }
    .load-error { max-width: 720px; }
    .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
  `],
})
export class WorkspaceSettingsComponent implements OnInit {
  readonly minDays = SHARE_POLICY_MIN_DAYS;
  readonly maxAllowedDays = SHARE_POLICY_MAX_DAYS;

  private readonly dayValidators = [
    Validators.required,
    Validators.min(SHARE_POLICY_MIN_DAYS),
    Validators.max(SHARE_POLICY_MAX_DAYS),
    Validators.pattern(/^\d+$/),
  ];

  form = this.fb.group({
    defaultDays: this.fb.control<number | null>(SHARE_POLICY_DEFAULT_DAYS, this.dayValidators),
    maxDays: this.fb.control<number | null>(SHARE_POLICY_MAX_DAYS, this.dayValidators),
  }, { validators: defaultWithinMax });

  policy: WorkspaceSharePolicy | null = null;
  loading = true;
  saving = false;
  loadError = '';
  saveError = '';

  constructor(
    private fb: FormBuilder,
    private api: AdminApiService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.loadError = '';
    this.api.getWorkspaceSharePolicy().subscribe({
      next: policy => {
        this.applyPolicy(policy);
        this.loading = false;
      },
      error: (err: HttpErrorResponse) => {
        this.loadError = this.describeError(err, 'Could not load the workspace sharing policy.');
        this.loading = false;
      },
    });
  }

  save(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid || this.saving) return;

    this.saving = true;
    this.saveError = '';
    const { defaultDays, maxDays } = this.form.getRawValue();
    this.api.updateWorkspaceSharePolicy({ defaultDays: Number(defaultDays), maxDays: Number(maxDays) }).subscribe({
      next: policy => {
        this.applyPolicy(policy);
        this.saving = false;
        this.snackBar.open('Workspace sharing policy saved', 'Dismiss', { duration: 3000 });
      },
      error: (err: HttpErrorResponse) => {
        this.saveError = this.describeError(err, 'Could not save the workspace sharing policy.');
        this.saving = false;
      },
    });
  }

  reset(): void {
    if (this.policy) this.applyPolicy(this.policy);
    this.saveError = '';
  }

  fieldError(name: 'defaultDays' | 'maxDays'): string {
    const errors = this.form.controls[name].errors;
    if (!errors) return '';
    if (errors['required']) return 'Enter a number of days.';
    if (errors['pattern']) return 'Use a whole number of days.';
    if (errors['min'] || errors['max']) {
      return `Must be between ${SHARE_POLICY_MIN_DAYS} and ${SHARE_POLICY_MAX_DAYS} days.`;
    }
    return 'Invalid value.';
  }

  private applyPolicy(policy: WorkspaceSharePolicy): void {
    this.policy = policy;
    this.form.reset({ defaultDays: policy.defaultDays, maxDays: policy.maxDays });
  }

  private describeError(err: HttpErrorResponse, fallback: string): string {
    if (err?.status === 403) return 'Only workspace owners can change sharing settings.';
    if (err?.status === 422) {
      const detail = this.extractApiMessage(err.error);
      return detail ? `The server rejected these values: ${detail}` : 'The server rejected these values.';
    }
    return this.extractApiMessage(err?.error) || fallback;
  }

  private extractApiMessage(body: any): string {
    if (!body) return '';
    if (typeof body === 'string') return body;
    const detail = body.detail ?? body.message ?? body.error;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map((d: any) => (typeof d === 'string' ? d : d?.msg)).filter(Boolean).join('; ');
    }
    return '';
  }
}
