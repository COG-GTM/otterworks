import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AdminApiService } from '../../core/services/admin-api.service';

@Component({
  selector: 'app-sharing',
  standalone: true,
  imports: [
    CommonModule, FormsModule, MatButtonModule, MatCardModule, MatFormFieldModule,
    MatInputModule, MatSnackBarModule,
  ],
  template: `
    <div class="page-container">
      <h1 class="page-title">Share Links</h1>
      <mat-card>
        <mat-card-content>
          <p class="hint">
            Default expiry for new document share links, and the range users may pick per link.
            Changes apply to new links only; existing links keep their expiry.
          </p>
          <div class="fields">
            <mat-form-field appearance="outline">
              <mat-label>Default expiry (days)</mat-label>
              <input matInput type="number" name="defaultDays" [(ngModel)]="defaultDays" min="1" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Minimum (days)</mat-label>
              <input matInput type="number" name="minDays" [(ngModel)]="minDays" min="1" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Maximum (days)</mat-label>
              <input matInput type="number" name="maxDays" [(ngModel)]="maxDays" min="1" />
            </mat-form-field>
          </div>
          <p class="error" *ngIf="error" role="alert">{{ error }}</p>
        </mat-card-content>
        <mat-card-actions>
          <button mat-flat-button color="primary" (click)="save()" [disabled]="saving">Save</button>
        </mat-card-actions>
      </mat-card>
    </div>
  `,
  styles: [`
    .fields { display: flex; gap: 16px; flex-wrap: wrap; }
    .hint { color: rgba(0, 0, 0, 0.6); margin-bottom: 16px; }
    .error { color: #c62828; }
  `],
})
export class SharingComponent implements OnInit {
  defaultDays = 7;
  minDays = 1;
  maxDays = 30;
  saving = false;
  error = '';

  constructor(private api: AdminApiService, private snackBar: MatSnackBar) {}

  ngOnInit(): void {
    this.api.getSharePolicy().subscribe({
      next: (p) => {
        this.defaultDays = p.default_expiry_days;
        this.minDays = p.min_expiry_days;
        this.maxDays = p.max_expiry_days;
      },
      error: () => (this.error = 'Could not load the share link policy'),
    });
  }

  save(): void {
    this.saving = true;
    this.error = '';
    this.api.updateSharePolicy({
      default_expiry_days: Number(this.defaultDays),
      min_expiry_days: Number(this.minDays),
      max_expiry_days: Number(this.maxDays),
    }).subscribe({
      next: () => {
        this.saving = false;
        this.snackBar.open('Share link policy saved', 'Close', { duration: 3000 });
      },
      error: (err) => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error = typeof detail === 'string' ? detail : 'Could not save the share link policy';
      },
    });
  }
}
