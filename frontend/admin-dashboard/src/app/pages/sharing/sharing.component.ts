import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, ValidatorFn, Validators,
} from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AdminApiService } from '../../core/services/admin-api.service';
import { SHARING_POLICY_LIMITS, SharingPolicy } from '../../core/models/sharing-policy.model';

const integerValidator: ValidatorFn = (control: AbstractControl): ValidationErrors | null =>
  control.value === null || control.value === '' || Number.isInteger(Number(control.value))
    ? null
    : { integer: true };

export const sharingPolicyValidator: ValidatorFn = (group: AbstractControl): ValidationErrors | null => {
  const min = Number(group.get('minExpiryDays')?.value);
  const max = Number(group.get('maxExpiryDays')?.value);
  const def = Number(group.get('defaultExpiryDays')?.value);
  if ([min, max, def].some(v => !Number.isFinite(v))) return null;
  const errors: ValidationErrors = {};
  if (min > max) errors['minAboveMax'] = true;
  else if (def < min || def > max) errors['defaultOutOfRange'] = { min, max };
  return Object.keys(errors).length ? errors : null;
};

export function serverErrorMessage(err: HttpErrorResponse): string {
  const body = err.error;
  if (typeof body === 'string' && body.trim()) return body;
  for (const key of ['error', 'message', 'detail']) {
    if (typeof body?.[key] === 'string' && body[key].trim()) return body[key];
  }
  const errors = body?.errors;
  if (Array.isArray(errors) && errors.length) return errors.join(' ');
  if (errors && typeof errors === 'object') {
    const parts = Object.entries(errors).map(([field, msgs]) =>
      `${field.replace(/_/g, ' ')} ${([] as unknown[]).concat(msgs).join(', ')}`);
    if (parts.length) return parts.join('. ');
  }
  return 'The sharing policy was rejected by the server.';
}

@Component({
  selector: 'app-sharing',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, MatCardModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatIconModule, MatProgressSpinnerModule, MatSnackBarModule,
  ],
  template: `
    <div class="page-container">
      <h1 class="page-title">Sharing</h1>
      <p class="page-subtitle">Control how long folder share links stay active in this workspace.</p>

      <div *ngIf="loading" class="loading-container">
        <mat-spinner diameter="40"></mat-spinner>
      </div>

      <div *ngIf="!loading && loadError" class="banner banner-error load-error" role="alert">
        <mat-icon>error_outline</mat-icon>
        <span>{{ loadError }}</span>
        <button mat-button color="primary" type="button" (click)="load()">Retry</button>
      </div>

      <mat-card *ngIf="!loading && !loadError" class="settings-card">
        <mat-card-header>
          <mat-card-title>Folder share link expiry</mat-card-title>
          <mat-card-subtitle>Allowed range: {{ limits.min }} to {{ limits.max }} days. Links can never be set to never expire.</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <div class="banner banner-info new-links-note">
            <mat-icon>info</mat-icon>
            <span>Changes apply only to new folder share links. Existing links keep the expiry date they were created with.</span>
          </div>

          <form [formGroup]="form" (ngSubmit)="save()" novalidate>
            <div class="fields">
              <mat-form-field appearance="outline">
                <mat-label>Default expiry (days)</mat-label>
                <input matInput type="number" formControlName="defaultExpiryDays" data-testid="default-expiry"
                       [min]="limits.min" [max]="limits.max" step="1">
                <mat-hint>Used when a link is created without picking an expiry</mat-hint>
                <mat-error>{{ fieldError('defaultExpiryDays') }}</mat-error>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Minimum expiry (days)</mat-label>
                <input matInput type="number" formControlName="minExpiryDays" data-testid="min-expiry"
                       [min]="limits.min" [max]="limits.max" step="1">
                <mat-hint>Shortest expiry a user can pick</mat-hint>
                <mat-error>{{ fieldError('minExpiryDays') }}</mat-error>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Maximum expiry (days)</mat-label>
                <input matInput type="number" formControlName="maxExpiryDays" data-testid="max-expiry"
                       [min]="limits.min" [max]="limits.max" step="1">
                <mat-hint>Longest expiry a user can pick</mat-hint>
                <mat-error>{{ fieldError('maxExpiryDays') }}</mat-error>
              </mat-form-field>
            </div>

            <div *ngIf="groupError" class="banner banner-error group-error" role="alert">
              <mat-icon>warning</mat-icon>
              <span>{{ groupError }}</span>
            </div>

            <div *ngIf="serverError" class="banner banner-error server-error" role="alert">
              <mat-icon>error_outline</mat-icon>
              <span>{{ serverError }}</span>
            </div>

            <div class="actions">
              <button mat-stroked-button type="button" (click)="reset()" [disabled]="saving || form.pristine">
                Reset
              </button>
              <button mat-flat-button color="primary" type="submit" data-testid="save"
                      [disabled]="saving || form.invalid || form.pristine">
                {{ saving ? 'Saving...' : 'Save changes' }}
              </button>
            </div>
          </form>
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .page-container { padding: 0; }
    .page-title { font-size: 1.5rem; font-weight: 600; color: #333; margin-bottom: 4px; }
    .page-subtitle { color: #666; margin: 0 0 24px; }
    .loading-container { display: flex; justify-content: center; padding: 60px; }

    .settings-card { max-width: 760px; }
    mat-card-content { padding-top: 16px; }

    .banner {
      display: flex; align-items: center; gap: 10px;
      padding: 12px 16px; border-radius: 4px; margin-bottom: 20px; font-size: 0.9rem;
    }
    .banner mat-icon { flex-shrink: 0; }
    .banner-info { background: #e7eaef; color: #1f3a5f; }
    .banner-error { background: #fdecea; color: #b71c1c; }
    .load-error { max-width: 760px; }

    .fields { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
    .actions { display: flex; justify-content: flex-end; gap: 12px; }

    @media (max-width: 900px) { .fields { grid-template-columns: 1fr; } }
  `],
})
export class SharingComponent implements OnInit {
  readonly limits = SHARING_POLICY_LIMITS;

  private readonly dayValidators = [
    Validators.required, integerValidator,
    Validators.min(SHARING_POLICY_LIMITS.min), Validators.max(SHARING_POLICY_LIMITS.max),
  ];

  readonly form = this.fb.group({
    defaultExpiryDays: [null as number | null, this.dayValidators],
    minExpiryDays: [null as number | null, this.dayValidators],
    maxExpiryDays: [null as number | null, this.dayValidators],
  }, { validators: sharingPolicyValidator });

  loading = true;
  saving = false;
  loadError: string | null = null;
  serverError: string | null = null;
  private saved: SharingPolicy | null = null;

  constructor(
    private api: AdminApiService,
    private fb: FormBuilder,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.loadError = null;
    this.api.getSharingPolicy().subscribe({
      next: policy => {
        this.applyPolicy(policy);
        this.loading = false;
      },
      error: (err: HttpErrorResponse) => {
        this.loadError = err.status === 403
          ? 'Only workspace owners can view the sharing policy.'
          : 'Could not load the sharing policy. Please try again.';
        this.loading = false;
      },
    });
  }

  save(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid || this.saving) return;
    const value = this.form.getRawValue();
    const policy: SharingPolicy = {
      defaultExpiryDays: Number(value.defaultExpiryDays),
      minExpiryDays: Number(value.minExpiryDays),
      maxExpiryDays: Number(value.maxExpiryDays),
    };
    this.saving = true;
    this.serverError = null;
    this.api.updateSharingPolicy(policy).subscribe({
      next: updated => {
        this.applyPolicy(updated);
        this.saving = false;
        this.snackBar.open('Sharing policy saved. It applies to new folder share links.', 'Dismiss', { duration: 4000 });
      },
      error: (err: HttpErrorResponse) => {
        this.saving = false;
        if (err.status === 422) this.serverError = serverErrorMessage(err);
        else if (err.status === 403) this.serverError = 'Only workspace owners can change the sharing policy.';
        else this.serverError = 'Could not save the sharing policy. Please try again.';
      },
    });
  }

  reset(): void {
    if (this.saved) this.applyPolicy(this.saved);
  }

  fieldError(name: 'defaultExpiryDays' | 'minExpiryDays' | 'maxExpiryDays'): string {
    const errors = this.form.controls[name].errors;
    if (!errors) return '';
    if (errors['required']) return 'Enter a number of days';
    if (errors['integer']) return 'Use whole days';
    if (errors['min'] || errors['max']) return `Must be between ${this.limits.min} and ${this.limits.max} days`;
    return '';
  }

  get groupError(): string | null {
    const errors = this.form.errors;
    if (!errors) return null;
    if (errors['minAboveMax']) return 'Minimum expiry cannot be greater than maximum expiry.';
    const range = errors['defaultOutOfRange'];
    if (range) return `Default expiry must be between the minimum (${range.min}) and maximum (${range.max}) days.`;
    return null;
  }

  private applyPolicy(policy: SharingPolicy): void {
    this.saved = policy;
    this.form.reset({ ...policy });
    this.serverError = null;
  }
}
