import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AbstractControl, FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { ErrorStateMatcher } from '@angular/material/core';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { SharePolicyService } from '../../core/services/share-policy.service';
import { SHARE_POLICY_LIMITS, SharePolicy, SharePolicyUpdate } from '../../core/models/share-policy.model';
import {
  expiryDaysValidators, sharePolicyErrorMessage, sharePolicyOrderValidator, sharePolicyViolation,
} from '../../core/validators/share-policy.validators';

type ExpiryField = 'defaultExpiryDays' | 'minExpiryDays' | 'maxExpiryDays';

/** Show field errors as soon as the owner edits a value, not only after blur. */
class DirtyErrorStateMatcher implements ErrorStateMatcher {
  isErrorState(control: AbstractControl | null): boolean {
    return !!control && control.invalid && (control.dirty || control.touched);
  }
}

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
        <button mat-stroked-button type="button" class="retry-btn" (click)="load()">Retry</button>
      </div>

      <mat-card *ngIf="!loading && policy" class="settings-card">
        <mat-card-header>
          <mat-icon mat-card-avatar class="card-icon">link</mat-icon>
          <mat-card-title>Share-link expiry</mat-card-title>
          <mat-card-subtitle>
            Workspace <code class="workspace-id">{{ policy.workspaceId }}</code>
            <span class="updated-meta" *ngIf="policy.updatedAt; else builtIn">
              &middot; Last changed {{ policy.updatedAt | date:'medium' }}<ng-container *ngIf="policy.updatedBy"> by {{ policy.updatedBy }}</ng-container>
            </span>
            <ng-template #builtIn><span class="updated-meta">&middot; Using built-in defaults</span></ng-template>
          </mat-card-subtitle>
        </mat-card-header>

        <mat-card-content>
          <p class="section-help">
            Set how long new share links stay valid by default, and the shortest and longest expiry
            people may choose when they create or edit a link.
          </p>

          <div class="ac7-note" role="note">
            <mat-icon>info</mat-icon>
            <span>
              Changes apply only to share links created after you save. Existing links keep their current
              expiry and are never expired retroactively; links created before expiry was introduced keep
              working with no expiry.
            </span>
          </div>

          <form [formGroup]="form" (ngSubmit)="save()" novalidate class="policy-form">
            <div class="fields">
              <mat-form-field appearance="outline" *ngFor="let f of fields">
                <mat-label>{{ f.label }}</mat-label>
                <input matInput type="number" step="1" [min]="limits.floorDays" [max]="limits.ceilingDays"
                       [formControlName]="f.key" [errorStateMatcher]="errorMatcher" [attr.data-testid]="f.key">
                <span matTextSuffix>days</span>
                <mat-hint>{{ f.hint }}</mat-hint>
                <mat-error *ngIf="fieldError(f.key) as msg">{{ msg }}</mat-error>
              </mat-form-field>
            </div>

            <div class="form-error" *ngIf="form.errors?.['minAboveDefault']" data-testid="min-above-default">
              <mat-icon>warning</mat-icon> Minimum expiry cannot be greater than the default expiry.
            </div>
            <div class="form-error" *ngIf="form.errors?.['defaultAboveMax']" data-testid="default-above-max">
              <mat-icon>warning</mat-icon> Default expiry cannot be greater than the maximum expiry.
            </div>

            <p class="preview" *ngIf="form.valid" data-testid="policy-preview">
              New links will expire after <strong>{{ form.value.defaultExpiryDays }}</strong>
              day{{ form.value.defaultExpiryDays === 1 ? '' : 's' }} unless the creator picks between
              <strong>{{ form.value.minExpiryDays }}</strong> and <strong>{{ form.value.maxExpiryDays }}</strong> days.
            </p>

            <div class="error-banner" *ngIf="saveError" role="alert" data-testid="save-error">
              <mat-icon>error_outline</mat-icon>
              <span>{{ saveError }}</span>
            </div>

            <div class="actions">
              <button mat-button type="button" (click)="reset()" [disabled]="saving || form.pristine">Reset</button>
              <button mat-flat-button color="primary" type="submit" data-testid="save-policy"
                      [disabled]="saving || form.invalid || form.pristine">
                <mat-spinner *ngIf="saving" diameter="18" class="btn-spinner"></mat-spinner>
                Save policy
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
    .settings-card { max-width: 860px; }
    .card-icon { color: #1f3a5f; font-size: 32px; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; }
    .workspace-id { background: #f1f3f5; padding: 1px 6px; border-radius: 3px; font-size: 0.85em; }
    .updated-meta { margin-left: 4px; }
    .section-help { color: #555; margin: 16px 0 12px; }
    .ac7-note {
      display: flex; gap: 10px; align-items: flex-start; background: #eef4fb; border-left: 3px solid #1f3a5f;
      padding: 12px 14px; border-radius: 4px; color: #1f3a5f; margin-bottom: 20px; font-size: 0.9rem;
    }
    .ac7-note mat-icon { flex-shrink: 0; }
    .fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
    .form-error { display: flex; align-items: center; gap: 6px; color: #c62828; font-size: 0.875rem; margin-top: 8px; }
    .form-error mat-icon { font-size: 18px; width: 18px; height: 18px; }
    .preview { color: #333; margin: 16px 0 0; }
    .error-banner {
      display: flex; align-items: center; gap: 10px; background: #fdecea; color: #b71c1c;
      padding: 12px 14px; border-radius: 4px; margin-top: 16px;
    }
    .load-error { max-width: 860px; margin-bottom: 16px; }
    .retry-btn { margin-left: auto; }
    .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
    .btn-spinner { display: inline-block; margin-right: 8px; vertical-align: middle; }
  `],
})
export class WorkspaceSettingsComponent implements OnInit {
  readonly limits = SHARE_POLICY_LIMITS;
  readonly errorMatcher = new DirtyErrorStateMatcher();
  readonly fields: { key: ExpiryField; label: string; hint: string }[] = [
    { key: 'defaultExpiryDays', label: 'Default expiry', hint: 'Applied when the creator does not pick an expiry' },
    { key: 'minExpiryDays', label: 'Minimum expiry', hint: `At least ${SHARE_POLICY_LIMITS.floorDays} day` },
    { key: 'maxExpiryDays', label: 'Maximum expiry', hint: `At most ${SHARE_POLICY_LIMITS.ceilingDays} days` },
  ];

  policy: SharePolicy | null = null;
  loading = true;
  saving = false;
  loadError: string | null = null;
  saveError: string | null = null;

  form: FormGroup;

  constructor(private fb: FormBuilder, private sharePolicy: SharePolicyService, private snackBar: MatSnackBar) {
    this.form = this.fb.group({
      defaultExpiryDays: [null, expiryDaysValidators],
      minExpiryDays: [null, expiryDaysValidators],
      maxExpiryDays: [null, expiryDaysValidators],
    }, { validators: sharePolicyOrderValidator });
    this.form.valueChanges.subscribe(() => { this.saveError = null; });
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.loadError = null;
    this.sharePolicy.getPolicy().subscribe({
      next: policy => {
        this.applyPolicy(policy);
        this.loading = false;
      },
      error: err => {
        this.loadError = `Could not load the share-link expiry policy. ${sharePolicyErrorMessage(err)}`;
        this.loading = false;
      },
    });
  }

  fieldError(key: ExpiryField): string | null {
    const errors = this.form.get(key)?.errors;
    if (!errors) return null;
    if (errors['required']) return 'Required';
    if (errors['pattern']) return 'Enter a whole number of days';
    if (errors['min']) return `Must be at least ${SHARE_POLICY_LIMITS.floorDays} day`;
    if (errors['max']) return `Cannot exceed ${SHARE_POLICY_LIMITS.ceilingDays} days`;
    return null;
  }

  save(): void {
    if (this.form.invalid || this.saving) return;
    const update: SharePolicyUpdate = {
      defaultExpiryDays: Number(this.form.value.defaultExpiryDays),
      minExpiryDays: Number(this.form.value.minExpiryDays),
      maxExpiryDays: Number(this.form.value.maxExpiryDays),
    };
    const violation = sharePolicyViolation(update);
    if (violation) {
      this.saveError = violation;
      return;
    }
    this.saving = true;
    this.saveError = null;
    this.sharePolicy.updatePolicy(update).subscribe({
      next: policy => {
        this.applyPolicy(policy);
        this.saving = false;
        this.snackBar.open('Share-link expiry policy saved. It applies to links created from now on.', 'Close', { duration: 4000 });
      },
      error: err => {
        this.saveError = sharePolicyErrorMessage(err);
        this.saving = false;
      },
    });
  }

  reset(): void {
    if (this.policy) this.applyPolicy(this.policy);
  }

  private applyPolicy(policy: SharePolicy): void {
    this.policy = policy;
    this.form.reset({
      defaultExpiryDays: policy.defaultExpiryDays,
      minExpiryDays: policy.minExpiryDays,
      maxExpiryDays: policy.maxExpiryDays,
    });
    this.saveError = null;
  }
}
