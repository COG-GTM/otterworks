import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AdminApiService } from '../../core/services/admin-api.service';
import { SharePolicy } from '../../core/models/share-policy.model';

@Component({
  selector: 'app-sharing',
  standalone: true,
  imports: [
    CommonModule, FormsModule, MatCardModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatSlideToggleModule, MatProgressSpinnerModule, MatSnackBarModule,
  ],
  template: `
    <div class="page-container">
      <h1 class="page-title">Sharing Settings</h1>
      <p class="subtitle">
        Workspace-wide expiry for read-only share links. Users can override the default per link
        within these bounds. Changes apply only to links created afterwards and are audited.
      </p>

      <div *ngIf="loading" class="loading-container">
        <mat-spinner diameter="40"></mat-spinner>
      </div>

      <mat-card *ngIf="!loading && policy" class="settings-card">
        <form (ngSubmit)="save()" #f="ngForm">
          <mat-slide-toggle name="allowNoExpiry" [(ngModel)]="policy.allowNoExpiry">
            Allow links that never expire
          </mat-slide-toggle>

          <div class="row">
            <mat-form-field appearance="outline">
              <mat-label>Default expiry (days)</mat-label>
              <input matInput type="number" min="1" name="defaultExpiryDays"
                     [(ngModel)]="policy.defaultExpiryDays"
                     [placeholder]="policy.allowNoExpiry ? 'Blank = never expires' : ''">
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Minimum (days)</mat-label>
              <input matInput type="number" min="1" name="minExpiryDays" required
                     [(ngModel)]="policy.minExpiryDays">
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Maximum (days)</mat-label>
              <input matInput type="number" min="1" name="maxExpiryDays"
                     [(ngModel)]="policy.maxExpiryDays" placeholder="Blank = no maximum">
            </mat-form-field>
          </div>

          <p class="error" *ngIf="error">{{ error }}</p>

          <button mat-flat-button color="primary" type="submit" [disabled]="saving">
            {{ saving ? 'Saving...' : 'Save' }}
          </button>
        </form>
      </mat-card>
    </div>
  `,
  styles: [`
    .page-title { font-size: 1.5rem; font-weight: 600; color: #333; margin-bottom: 8px; }
    .subtitle { color: #666; margin-bottom: 24px; max-width: 720px; }
    .loading-container { display: flex; justify-content: center; padding: 60px; }
    .settings-card { max-width: 760px; padding: 24px; }
    .row { display: flex; gap: 16px; margin-top: 24px; flex-wrap: wrap; }
    .row mat-form-field { flex: 1; min-width: 180px; }
    .error { color: #c62828; margin: 0 0 16px; }
  `],
})
export class SharingComponent implements OnInit {
  policy: SharePolicy | null = null;
  loading = true;
  saving = false;
  error: string | null = null;

  constructor(private api: AdminApiService, private snackBar: MatSnackBar) {}

  ngOnInit(): void {
    this.api.getSharePolicy().subscribe({
      next: policy => { this.policy = policy; this.loading = false; },
      error: () => { this.error = 'Could not load sharing settings.'; this.loading = false; },
    });
  }

  save(): void {
    if (!this.policy) return;
    this.saving = true;
    this.error = null;
    this.api.updateSharePolicy(normalize(this.policy)).subscribe({
      next: policy => {
        this.policy = policy;
        this.saving = false;
        this.snackBar.open('Sharing settings saved', 'Close', { duration: 3000 });
      },
      error: err => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error = typeof detail === 'string'
          ? detail
          : err?.status === 403
            ? 'Only workspace owners can change sharing settings.'
            : 'Could not save sharing settings.';
      },
    });
  }
}

function toDays(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function normalize(policy: SharePolicy): SharePolicy {
  return {
    ...policy,
    defaultExpiryDays: toDays(policy.defaultExpiryDays),
    minExpiryDays: toDays(policy.minExpiryDays) ?? 1,
    maxExpiryDays: toDays(policy.maxExpiryDays),
  };
}
