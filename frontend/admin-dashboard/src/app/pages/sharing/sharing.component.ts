import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AdminApiService } from '../../core/services/admin-api.service';
import {
  DAY_SECONDS, HOUR_SECONDS, SharePolicy, SharePolicyUpdate, validateSharePolicy,
} from '../../core/models/share-policy.model';

export type DurationUnit = 'hours' | 'days';

export interface DurationField {
  value: number | null;
  unit: DurationUnit;
}

export interface SharePolicyForm {
  defaultExpiry: DurationField;
  minExpiry: DurationField;
  maxExpiry: DurationField;
  allowNever: boolean;
}

const UNIT_SECONDS: Record<DurationUnit, number> = { hours: HOUR_SECONDS, days: DAY_SECONDS };

export function toDurationField(seconds: number): DurationField {
  return seconds % DAY_SECONDS === 0
    ? { value: seconds / DAY_SECONDS, unit: 'days' }
    : { value: seconds / HOUR_SECONDS, unit: 'hours' };
}

export function toSeconds(field: DurationField): number {
  return field.value === null || field.value === undefined ? NaN : Math.round(field.value * UNIT_SECONDS[field.unit]);
}

export function formatDuration(seconds: number): string {
  const { value, unit } = toDurationField(seconds);
  const n = Number(value);
  return `${n} ${n === 1 ? unit.slice(0, -1) : unit}`;
}

@Component({
  selector: 'app-sharing',
  standalone: true,
  imports: [
    CommonModule, FormsModule, MatCardModule, MatIconModule, MatButtonModule, MatInputModule,
    MatFormFieldModule, MatSelectModule, MatSlideToggleModule, MatProgressSpinnerModule, MatSnackBarModule,
  ],
  template: `
    <div class="page-container">
      <h1 class="page-title">Sharing</h1>
      <p class="page-subtitle">Expiry rules for folder share links in this workspace. Changes apply to new links only.</p>

      <div *ngIf="loading" class="loading-container">
        <mat-spinner diameter="40"></mat-spinner>
      </div>

      <div *ngIf="!loading && loadError" class="banner banner-error" data-test="load-error">
        <mat-icon>error_outline</mat-icon><span>{{ loadError }}</span>
      </div>

      <mat-card *ngIf="!loading && form" class="settings-card">
        <mat-card-content>
          <h3 class="section-title">Folder share link expiry</h3>

          <div class="field-row" *ngFor="let f of fields">
            <div class="field-label">
              <div class="label">{{ f.label }}</div>
              <div class="hint">{{ f.hint }}</div>
            </div>
            <mat-form-field appearance="outline" class="value-field">
              <input matInput type="number" min="1" step="1" [name]="f.key + 'Value'" [attr.data-test]="f.key + '-value'"
                     [(ngModel)]="form[f.key].value" (ngModelChange)="onEdit()" [attr.aria-label]="f.label">
            </mat-form-field>
            <mat-form-field appearance="outline" class="unit-field">
              <mat-select [name]="f.key + 'Unit'" [attr.data-test]="f.key + '-unit'"
                          [(ngModel)]="form[f.key].unit" (ngModelChange)="onEdit()" [attr.aria-label]="f.label + ' unit'">
                <mat-option value="hours">hours</mat-option>
                <mat-option value="days">days</mat-option>
              </mat-select>
            </mat-form-field>
          </div>

          <div class="field-row">
            <div class="field-label">
              <div class="label">Allow links that never expire</div>
              <div class="hint">When off, every folder share link must have an expiry date.</div>
            </div>
            <mat-slide-toggle color="primary" name="allowNever" data-test="allow-never"
                              [(ngModel)]="form.allowNever" (ngModelChange)="onEdit()">
              {{ form.allowNever ? 'On' : 'Off' }}
            </mat-slide-toggle>
          </div>

          <ul *ngIf="clientErrors.length" class="banner banner-warn" data-test="client-errors">
            <li *ngFor="let e of clientErrors"><mat-icon>warning_amber</mat-icon><span>{{ e }}</span></li>
          </ul>

          <div *ngIf="serverError" class="banner banner-error" data-test="server-error">
            <mat-icon>error_outline</mat-icon><span>{{ serverError }}</span>
          </div>

          <div *ngIf="savedMessage" class="banner banner-ok" data-test="saved-message">
            <mat-icon>check_circle</mat-icon><span>{{ savedMessage }}</span>
          </div>

          <div class="actions">
            <span class="meta" *ngIf="policy?.updatedAt" data-test="last-updated">
              Last updated {{ policy?.updatedAt | date:'medium' }}<ng-container *ngIf="policy?.updatedBy"> by {{ policy?.updatedBy }}</ng-container>
            </span>
            <span class="meta" *ngIf="policy && !policy.updatedAt">Using workspace defaults</span>
            <span class="spacer"></span>
            <button mat-button type="button" (click)="reset()" [disabled]="saving || !dirty" data-test="reset">Reset</button>
            <button mat-flat-button color="primary" type="button" (click)="save()"
                    [disabled]="saving || !dirty || clientErrors.length > 0" data-test="save">
              {{ saving ? 'Saving…' : 'Save changes' }}
            </button>
          </div>
        </mat-card-content>
      </mat-card>

      <p *ngIf="!loading && policy" class="summary" data-test="summary">
        New links expire after {{ summary.default }} by default. Users can pick between {{ summary.min }} and
        {{ summary.max }}{{ policy.allowNever ? ', or no expiry' : '' }}.
      </p>
    </div>
  `,
  styles: [`
    .page-title { font-size: 1.5rem; font-weight: 600; color: #333; margin-bottom: 4px; }
    .page-subtitle { color: #666; margin-bottom: 24px; }
    .loading-container { display: flex; justify-content: center; padding: 60px; }
    .settings-card { max-width: 760px; }
    .section-title { font-size: 1rem; font-weight: 600; margin-bottom: 16px; }
    .field-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid #eee; }
    .field-label { flex: 1; }
    .label { font-weight: 500; }
    .hint, .meta { font-size: 0.8rem; color: #888; }
    .value-field { width: 110px; }
    .unit-field { width: 120px; }
    .value-field, .unit-field { margin-bottom: -1.25em; }
    .banner { display: flex; flex-direction: column; gap: 4px; list-style: none; padding: 10px 12px; margin-top: 16px; border-radius: 4px; }
    .banner li, div.banner { display: flex; flex-direction: row; align-items: center; gap: 8px; }
    .banner .mat-icon { font-size: 18px; width: 18px; height: 18px; }
    .banner-error { background: #fdecea; color: #b3261e; }
    .banner-warn { background: #fff4e5; color: #8a5300; }
    .banner-ok { background: #e8f5e9; color: #1b5e20; }
    .actions { display: flex; align-items: center; gap: 8px; margin-top: 20px; }
    .spacer { flex: 1; }
    .summary { max-width: 760px; margin-top: 12px; color: #555; }
  `],
})
export class SharingComponent implements OnInit {
  readonly fields: { key: 'defaultExpiry' | 'minExpiry' | 'maxExpiry'; label: string; hint: string }[] = [
    { key: 'defaultExpiry', label: 'Default expiry', hint: 'Applied when a user does not choose an expiry.' },
    { key: 'minExpiry', label: 'Minimum expiry', hint: 'Shortest expiry a user can choose.' },
    { key: 'maxExpiry', label: 'Maximum expiry', hint: 'Longest expiry a user can choose (up to 365 days).' },
  ];

  policy: SharePolicy | null = null;
  form: SharePolicyForm | null = null;
  loading = true;
  saving = false;
  dirty = false;
  loadError: string | null = null;
  serverError: string | null = null;
  savedMessage: string | null = null;

  constructor(private api: AdminApiService, private snackBar: MatSnackBar) {}

  ngOnInit(): void {
    this.api.getSharePolicy().subscribe({
      next: policy => {
        this.applyPolicy(policy);
        this.loading = false;
      },
      error: () => {
        this.loadError = 'Could not load sharing settings. Refresh the page to try again.';
        this.loading = false;
      },
    });
  }

  get clientErrors(): string[] {
    return this.form ? validateSharePolicy(this.toUpdate(this.form)) : [];
  }

  get summary(): { default: string; min: string; max: string } {
    const u = this.policy!;
    return {
      default: formatDuration(u.defaultExpirySeconds),
      min: formatDuration(u.minExpirySeconds),
      max: formatDuration(u.maxExpirySeconds),
    };
  }

  onEdit(): void {
    this.dirty = true;
    this.serverError = null;
    this.savedMessage = null;
  }

  reset(): void {
    if (this.policy) this.applyPolicy(this.policy);
  }

  save(): void {
    if (!this.form || this.clientErrors.length || this.saving) return;
    this.saving = true;
    this.serverError = null;
    this.savedMessage = null;
    this.api.updateSharePolicy(this.toUpdate(this.form)).subscribe({
      next: policy => {
        this.saving = false;
        this.applyPolicy(policy);
        this.savedMessage = 'Sharing settings saved.';
        this.snackBar.open('Sharing settings saved', 'Dismiss', { duration: 3000 });
      },
      error: (err: unknown) => {
        this.saving = false;
        this.serverError = this.errorMessage(err);
      },
    });
  }

  private applyPolicy(policy: SharePolicy): void {
    this.policy = policy;
    this.form = {
      defaultExpiry: toDurationField(policy.defaultExpirySeconds),
      minExpiry: toDurationField(policy.minExpirySeconds),
      maxExpiry: toDurationField(policy.maxExpirySeconds),
      allowNever: policy.allowNever,
    };
    this.dirty = false;
    this.serverError = null;
  }

  private toUpdate(form: SharePolicyForm): SharePolicyUpdate {
    return {
      defaultExpirySeconds: toSeconds(form.defaultExpiry),
      minExpirySeconds: toSeconds(form.minExpiry),
      maxExpirySeconds: toSeconds(form.maxExpiry),
      allowNever: form.allowNever,
    };
  }

  private errorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 403) return 'Only workspace owners can change sharing settings.';
      if (err.status === 422) {
        const detail = err.error?.detail;
        if (typeof detail === 'string' && detail) return detail;
        if (Array.isArray(detail) && detail.length) {
          return detail.map((d: any) => d?.msg ?? String(d)).join(' ');
        }
        return 'These sharing settings are not valid.';
      }
    }
    return 'Could not save sharing settings. Try again.';
  }
}
